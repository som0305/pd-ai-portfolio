#!/usr/bin/env python3
"""
OpenSTA(OpenROAD) 타이밍 리포트 파서

사용법:
    python3 parse_sta.py data/period_fast.rpt              # 요약 출력
    python3 parse_sta.py data/period_fast.rpt --json out.json   # JSON 저장

하는 일:
  1) 리포트 전체 지표 추출 (WNS, TNS, setup/hold 위반 개수, fmax 등)
  2) report_checks 경로를 셀 단위로 쪼개서 정리
  3) 경로마다 '분석에 쓸 숫자'를 계산
     - cell delay 합 vs wire delay 합 (OpenSTA는 입력핀 줄의 Delay = wire delay)
     - logic depth(셀 개수), 가장 느린 셀 Top3, 최대 fanout
     - launch/capture 클럭 latency, skew, setup time
이 JSON이 다음 단계에서 LLM에 들어갈 입력이 됩니다.
"""
import argparse
import json
import re
import sys

# ---------------------------------------------------------------- 1. 전체 지표
SCALAR_PATTERNS = {
    "tns": r"tns max\s+(-?[\d.]+)",
    "wns": r"wns max\s+(-?[\d.]+)",
    "worst_slack": r"worst slack max\s+(-?[\d.]+)",
    "setup_violation_count": r"setup violation count\s+(\d+)",
    "hold_violation_count": r"hold violation count\s+(\d+)",
    "max_slew_violation_count": r"max slew violation count\s+(\d+)",
    "max_cap_violation_count": r"max cap violation count\s+(\d+)",
    "max_fanout_violation_count": r"max fanout violation count\s+(\d+)",
}


def parse_scalars(text):
    out = {}
    for key, pat in SCALAR_PATTERNS.items():
        m = re.search(pat, text)
        if m:
            out[key] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
    # 클럭별 최소 주기 / fmax
    out["clock_min_period"] = {
        m.group(1): {"period_min": float(m.group(2)), "fmax": m.group(3)}
        for m in re.finditer(r"^(\S+) period_min = ([\d.]+) fmax = (\S+)", text, re.M)
    }
    return out


# ---------------------------------------------------------------- 2. 경로 파싱
# 섹션 구분: "=====" 다음 줄이 섹션 이름 (예: "finish report_checks -path_delay max")
SECTION_RE = re.compile(r"^=+\n(.+)\n-+\n", re.M)

# 핀 한 줄: 숫자들 + 엣지(^/v) + 핀 이름 + (셀 이름 또는 in/out)
PIN_RE = re.compile(r"^\s*([-\d.\s]+?)\s+([\^v])\s+(\S+)\s+\(([^)]+)\)\s*$")


def split_sections(text):
    parts = SECTION_RE.split(text)
    # parts = [앞부분, 이름1, 본문1, 이름2, 본문2, ...]
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def parse_pin_row(line):
    m = PIN_RE.match(line)
    if not m:
        return None
    nums = [float(x) for x in m.group(1).split()]
    edge, pin, cell = m.group(2), m.group(3), m.group(4)
    row = {"pin": pin, "cell": cell, "edge": "rise" if edge == "^" else "fall"}
    if len(nums) == 5:      # 출력핀/포트 줄: Fanout Cap Slew Delay Time
        row.update(fanout=int(nums[0]), cap=nums[1], slew=nums[2],
                   delay=nums[3], time=nums[4], kind="out")
    elif len(nums) == 3:    # 입력핀 줄: Slew Delay Time  (Delay = wire delay)
        row.update(slew=nums[0], delay=nums[1], time=nums[2], kind="in")
    elif len(nums) == 2:    # 간략 형식(Delay Time만 있는 리포트)
        row.update(delay=nums[0], time=nums[1], kind="short")
    else:
        return None
    return row


def parse_path_block(block):
    """Startpoint ~ slack 까지 한 경로를 dict로."""
    p = {}
    m = re.search(r"Startpoint: (\S+)\s*\n?\s*\(([^)]*)\)", block)
    if m:
        p["startpoint"], p["startpoint_type"] = m.group(1), m.group(2)
    m = re.search(r"Endpoint: (\S+)\s*\n?\s*\(([^)]*)\)", block)
    if m:
        p["endpoint"], p["endpoint_type"] = m.group(1), m.group(2)
    for key, label in (("path_group", "Path Group"), ("path_type", "Path Type")):
        m = re.search(label + r": (\S+)", block)
        if m:
            p[key] = m.group(1)

    m = re.search(r"(-?[\d.]+)\s+slack \((\w+)\)", block)
    if m:
        p["slack"], p["status"] = float(m.group(1)), m.group(2)
    m = re.search(r"^\s*(-?[\d.]+)\s+data required time", block, re.M)
    if m:
        p["required_time"] = float(m.group(1))
    m = re.search(r"^\s*(-?[\d.]+)\s+data arrival time", block, re.M)
    if m:
        p["arrival_time"] = float(m.group(1))
    m = re.search(r"(-?[\d.]+)\s+-?[\d.]+\s+library (setup|hold) time", block)
    if m:
        p["library_" + m.group(2) + "_time"] = abs(float(m.group(1)))
    m = re.search(r"(-?[\d.]+)\s+-?[\d.]+\s+output external delay", block)
    if m:
        p["output_external_delay"] = abs(float(m.group(1)))
    m = re.search(r"(-?[\d.]+)\s+-?[\d.]+\s+.?\s*input external delay", block)
    if m:
        p["input_external_delay"] = abs(float(m.group(1)))

    # launch(arrival) 구간과 capture(required) 구간 나누기
    lines = block.splitlines()
    launch, capture, phase = [], [], "launch"
    for ln in lines:
        if "data arrival time" in ln and phase == "launch":
            phase = "capture"
            continue
        if "data required time" in ln:
            phase = "done"
        row = parse_pin_row(ln)
        if row:
            (launch if phase == "launch" else capture if phase == "capture" else []).append(row)

    # 데이터 경로 = launch 플롭의 CLK 핀 다음부터 (입력포트 시작이면 포트부터)
    clk_idx = next((i for i, r in enumerate(launch) if r["pin"].endswith("/CLK")), None)
    if clk_idx is not None:
        p["launch_clock_latency"] = launch[clk_idx]["time"]
        data = launch[clk_idx + 1:]
    else:
        data = [r for r in launch if r["cell"] not in ("in",) or r["pin"] == p.get("startpoint")]
    cap_clk = next((r for r in capture if r["pin"].endswith("/CLK")), None)
    if cap_clk:
        # capture 쪽 시간 = 클럭 엣지 + latency → 엣지를 빼서 latency만
        m = re.search(r"([\d.]+)\s+[\d.]+\s+clock \S+ \(rise edge\)", "\n".join(
            ln for ln in lines[lines.index(next(ln for ln in lines if "data arrival time" in ln)):]))
        edge_t = float(m.group(1)) if m else 0.0
        p["capture_clock_latency"] = round(cap_clk["time"] - edge_t, 4)
        p["clock_period_used"] = edge_t
    if "launch_clock_latency" in p and "capture_clock_latency" in p:
        p["clock_skew"] = round(p["capture_clock_latency"] - p["launch_clock_latency"], 4)

    p["stages"] = data
    p["metrics"] = path_metrics(data)
    return p


def path_metrics(stages):
    cells = [s for s in stages if s["kind"] == "out" and s["cell"] not in ("in", "out")]
    wires = [s for s in stages if s["kind"] == "in"]
    cell_delay = sum(s["delay"] for s in cells)
    wire_delay = sum(s["delay"] for s in wires)
    total = cell_delay + wire_delay
    top = sorted(cells, key=lambda s: s["delay"], reverse=True)[:3]
    return {
        "logic_depth": len(cells),
        "data_path_delay": round(total, 4),
        "cell_delay_sum": round(cell_delay, 4),
        "wire_delay_sum": round(wire_delay, 4),
        "wire_delay_ratio": round(wire_delay / total, 3) if total else 0,
        "max_fanout": max((s["fanout"] for s in cells), default=0),
        "max_slew": max((s["slew"] for s in stages if "slew" in s), default=0),
        "slowest_cells": [
            {"pin": s["pin"], "cell": s["cell"], "delay": s["delay"],
             "fanout": s["fanout"], "cap": s["cap"]} for s in top],
        "inserted_buffers": [s["pin"] for s in cells
                             if re.search(r"(^|/)(place|rebuffer|split|wire)\w*\d", s["pin"])],
    }


def parse_paths(text):
    paths, seen = [], set()
    for name, body in split_sections(text):
        if "report_checks" not in name or "Startpoint:" not in body:
            continue
        # 상세 형식(Fanout/Cap/Slew 열이 있는 것)만 사용. 간략 형식은 중복이라 생략
        if "Fanout" not in body:
            continue
        for blk in re.split(r"(?=^Startpoint:)", body, flags=re.M):
            if not blk.startswith("Startpoint:"):
                continue
            p = parse_path_block(blk)
            key = (p.get("startpoint"), p.get("endpoint"), p.get("path_type"))
            if key in seen:          # -unconstrained 섹션 등 중복 제거
                continue
            seen.add(key)
            p["section"] = name
            paths.append(p)
    return paths


def parse_report(text):
    return {"summary": parse_scalars(text), "paths": parse_paths(text)}


# ---------------------------------------------------------------- 3. 출력
def print_summary(r):
    s = r["summary"]
    print("=== 전체 요약 ===")
    for k in ("wns", "tns", "setup_violation_count", "hold_violation_count",
              "max_slew_violation_count", "max_cap_violation_count"):
        if k in s:
            print(f"  {k:28s} {s[k]}")
    for clk, v in s.get("clock_min_period", {}).items():
        print(f"  {clk:28s} period_min={v['period_min']} fmax={v['fmax']}")
    for p in r["paths"]:
        m = p["metrics"]
        print(f"\n=== [{p['path_type']}] {p['startpoint']} -> {p['endpoint']} ===")
        print(f"  group={p.get('path_group')}  slack={p.get('slack')} ({p.get('status')})")
        print(f"  arrival={p.get('arrival_time')}  required={p.get('required_time')}"
              f"  skew={p.get('clock_skew', '-')}")
        print(f"  logic_depth={m['logic_depth']}  data_path={m['data_path_delay']}"
              f"  cell={m['cell_delay_sum']}  wire={m['wire_delay_sum']}"
              f"  (wire {m['wire_delay_ratio']*100:.0f}%)")
        print(f"  max_fanout={m['max_fanout']}  max_slew={m['max_slew']}"
              f"  buffers={m['inserted_buffers']}")
        print("  slowest:")
        for c in m["slowest_cells"]:
            print(f"    {c['delay']:.2f}ns  {c['cell']:28s} fo={c['fanout']}  {c['pin']}")


def main():
    ap = argparse.ArgumentParser(description="OpenSTA 리포트 파서")
    ap.add_argument("report")
    ap.add_argument("--json", help="결과를 JSON 파일로 저장")
    a = ap.parse_args()
    with open(a.report, encoding="utf-8", errors="replace") as f:
        r = parse_report(f.read())
    r["source"] = a.report
    print_summary(r)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        print(f"\nJSON 저장: {a.json}")


if __name__ == "__main__":
    main()
