#!/usr/bin/env python3
"""
AI 타이밍 분석기: parse_sta.py가 만든 JSON을 Claude(claude -p)에 보내 원인 분석을 받는다.

사용법:
    python3 analyze_sta.py data/period_fast.json             # 한 개
    python3 analyze_sta.py data/period_*.json                # 여러 개
    python3 analyze_sta.py data/period_fast.json --dry-run   # AI 호출 없이 프롬프트만 확인

결과:
    results/<이름>.ai.json   구조화된 분석 결과 (나중에 내 판단과 비교할 때 사용)
    results/<이름>.ai.md     사람이 읽기 좋은 버전

동작 원리:
  1) JSON에서 분석에 필요한 것만 골라 짧은 입력으로 만든다 (setup(max) 경로 중심)
  2) 'PD 엔지니어로서 원인을 분류하라'는 지시문 + 데이터를 claude -p에 넘긴다
  3) --json-schema로 답의 형식을 고정해서, 매번 같은 구조로 결과를 받는다
"""
import argparse
import json
import os
import subprocess
import sys

CATEGORIES = [
    "logic_depth",      # 조합 로직 단수가 너무 많음
    "slow_cell",        # 특정 셀(구동력 약한 셀, 느린 플롭 등) 지연이 큼
    "high_fanout",      # 큰 fanout/부하로 인한 지연
    "long_wire",        # 배선 지연 (입력핀 줄의 Delay)
    "clock_skew",       # launch/capture 클럭 latency 차이
    "io_constraint",    # input/output delay 제약이 빡빡함
    "other",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "overall_summary": {"type": "string"},
        "paths": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "startpoint": {"type": "string"},
                    "endpoint": {"type": "string"},
                    "slack": {"type": "number"},
                    "root_causes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {"type": "string", "enum": CATEGORIES},
                                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                                "evidence": {"type": "string"},
                            },
                            "required": ["category", "confidence", "evidence"],
                        },
                    },
                    "pd_fixes": {"type": "array", "items": {"type": "string"}},
                    "rtl_or_constraint_fixes": {"type": "array", "items": {"type": "string"}},
                    "closable_by_pd_only": {"type": "boolean"},
                    "reasoning": {"type": "string"},
                },
                "required": ["startpoint", "endpoint", "slack", "root_causes",
                             "pd_fixes", "rtl_or_constraint_fixes",
                             "closable_by_pd_only", "reasoning"],
            },
        },
    },
    "required": ["overall_summary", "paths"],
}

INSTRUCTIONS = f"""너는 10년차 physical design / STA 엔지니어다.
아래는 OpenROAD(OpenSTA)로 sky130hd 공정에서 구현한 디자인의 finish 단계 타이밍 리포트를 파싱한 데이터다.

데이터 읽는 법:
- stages의 kind="out"은 셀 출력핀 → delay는 셀 지연
- kind="in"은 셀 입력핀 → delay는 그 앞 배선(wire) 지연
- clock_skew = capture latency - launch latency
- inserted_buffers는 툴이 최적화 중 넣은 버퍼

할 일:
1. setup(path_type=max) 경로마다 위반 원인을 아래 카테고리로 분류하고, 반드시 데이터의 숫자를 근거로 써라.
   카테고리: {", ".join(CATEGORIES)}
2. PD 단계에서 할 수 있는 조치(사이징, 버퍼링, 배치, useful skew 등)와
   RTL/제약 수준 조치(파이프라이닝, 구조 변경, 클럭 목표 조정 등)를 나눠서 제안하라.
3. 위반 크기와 경로 구성을 볼 때 PD 조치만으로 닫을 수 있는지 판단하라.
4. 위반이 없으면 여유(margin)가 어디서 생겼는지, 다음 병목이 될 경로가 무엇인지 설명하라.
추측이면 confidence를 낮게 줘라. 모든 설명은 한국어로.
"""


def compact(report):
    """LLM 입력을 짧게: setup 경로 위주, 필요한 필드만."""
    keep = ("pin", "cell", "kind", "fanout", "cap", "slew", "delay", "time")
    paths = []
    for p in report["paths"]:
        if p.get("path_type") != "max":
            continue
        q = {k: v for k, v in p.items() if k not in ("stages", "section")}
        q["stages"] = [{k: s[k] for k in keep if k in s} for s in p["stages"]]
        paths.append(q)
    return {"source": report.get("source"), "summary": report["summary"], "setup_paths": paths}


def call_claude(prompt, data):
    cmd = ["claude", "-p", prompt,
           "--output-format", "json",
           "--json-schema", json.dumps(SCHEMA)]
    proc = subprocess.run(cmd, input=json.dumps(data, ensure_ascii=False),
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"claude 실행 실패:\n{proc.stderr or proc.stdout}")
    out = json.loads(proc.stdout)
    if out.get("is_error") or "structured_output" not in out:
        raise RuntimeError(f"AI 응답 오류:\n{json.dumps(out, ensure_ascii=False)[:1000]}")
    return out["structured_output"]


def to_markdown(name, data, ai):
    s = data["summary"]
    lines = [f"# AI 타이밍 분석: {name}", "",
             f"- WNS: {s.get('wns')} / TNS: {s.get('tns')} / setup 위반: {s.get('setup_violation_count')}",
             "", "## 전체 요약", ai["overall_summary"], ""]
    for p in ai["paths"]:
        lines += [f"## {p['startpoint']} → {p['endpoint']} (slack {p['slack']})", "",
                  "**원인**"]
        lines += [f"- `{c['category']}` ({c['confidence']}): {c['evidence']}" for c in p["root_causes"]]
        lines += ["", "**PD 조치**"] + [f"- {x}" for x in p["pd_fixes"]]
        lines += ["", "**RTL/제약 조치**"] + [f"- {x}" for x in p["rtl_or_constraint_fixes"]]
        lines += ["", f"**PD만으로 해결 가능?** {'예' if p['closable_by_pd_only'] else '아니오'}",
                  "", p["reasoning"], ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="AI 타이밍 분석기")
    ap.add_argument("files", nargs="+", help="parse_sta.py가 만든 JSON")
    ap.add_argument("--out", default="results", help="결과 폴더 (기본: results)")
    ap.add_argument("--dry-run", action="store_true", help="AI 호출 없이 입력만 출력")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    for path in a.files:
        name = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as f:
            data = compact(json.load(f))
        if a.dry_run:
            print(INSTRUCTIONS)
            print(json.dumps(data, ensure_ascii=False, indent=1)[:3000], "...")
            continue
        print(f"[{name}] 분석 중... (30초~1분)")
        try:
            ai = call_claude(INSTRUCTIONS, data)
        except Exception as e:
            print(f"[{name}] 실패: {e}", file=sys.stderr)
            continue
        with open(os.path.join(a.out, name + ".ai.json"), "w", encoding="utf-8") as f:
            json.dump(ai, f, ensure_ascii=False, indent=2)
        with open(os.path.join(a.out, name + ".ai.md"), "w", encoding="utf-8") as f:
            f.write(to_markdown(name, data, ai))
        print(f"[{name}] 완료 → {a.out}/{name}.ai.md")


if __name__ == "__main__":
    main()
