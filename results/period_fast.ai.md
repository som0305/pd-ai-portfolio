# AI 타이밍 분석: period_fast

- WNS: -1.65 / TNS: -88.09 / setup 위반: 85

## 전체 요약
core_clock 목표 주기 0.7ns(≈1.43GHz)에서 WNS -1.65ns, TNS -88.09ns이고 setup 위반 endpoint는 85개입니다(평균 slack 약 -1.04ns). 위반이 일부 경로가 아니라 디자인 전반에 퍼져 있습니다. 리포트가 계산한 최소 주기는 2.35ns(Fmax 426.44MHz)로, 0.7 + 1.65 = 2.35와 정확히 맞습니다. 결정적인 근거는 플롭 오버헤드입니다. sky130_fd_sc_hd__edfxtp_1의 clk→Q 0.40~0.43ns와 library setup 0.24ns를 합치면 약 0.64ns로 주기의 91%를 차지해, 조합 로직에 남는 시간은 약 0.05ns뿐입니다. 두 경로 모두 배선 지연 합은 0.00(wire_delay_ratio 0), clock skew는 -0.01ns라서 배선과 클럭 트리는 원인이 아닙니다. 지연의 대부분은 _119_ 뺄셈기/비교기(GCD dpath로 보임)의 로직 깊이(10~11단)와 일부 느린 셀(maj3_4 0.40ns, nor4_1 0.29ns), 그리고 툴이 삽입한 버퍼에서 나옵니다. hold, max slew, max cap, max fanout 위반은 0건이라 DRV 정리는 끝난 상태입니다. 사이징, 버퍼 정리, 플롭 교체, useful skew를 모두 동원해도 개선 폭은 0.3~0.5ns 정도로 추정되며(추정치), 필요한 1.65ns에 크게 못 미치므로 PD 조치만으로는 닫을 수 없습니다. 권고: (1) 클럭 목표를 최소 2.35ns 이상, 현실적으로는 약 2.5ns로 조정합니다. (2) 0.7ns가 반드시 필요하다면 단계당 게이트 1~2단 수준의 극단적인 파이프라이닝이 필요해 비현실적이므로, 뺄셈기 구조 변경, 비교와 뺄셈 분리, 출력 레지스터화를 함께 검토해야 합니다. 주기를 2.5ns 수준으로 완화하면 이번 두 경로 계열(b_reg→뺄셈기→a_reg 피드백, b_reg→뺄셈기→resp_msg 출력)이 그대로 다음 병목이 될 가능성이 높습니다.

## dpath.b_reg.out[0]$_DFFE_PP_ → dpath.a_reg.out[14]$_DFFE_PP_ (slack -1.65)

**원인**
- `logic_depth` (high): logic_depth 10단, data_path_delay 2.09ns. 쓸 수 있는 시간은 period 0.7 - setup 0.24 - |skew| 0.01 = 0.45ns인데 데이터 경로가 약 4.6배입니다. xnor2→maj3→o21ai→a21oi→o21ai→a21o로 이어지는 carry 체인만 0.18+0.40+0.18+0.10+0.17+0.24 = 1.27ns로 data path의 61%를 차지합니다. maj3과 aoi/oai가 번갈아 나오는 패턴으로 보아 ripple 계열 뺄셈기 carry 전파로 판단됩니다.
- `slow_cell` (medium): maj3_4 한 셀이 0.40ns(fanout 4, cap 0.03)입니다. 입력 slew가 0.09로 양호한데도 지연이 커서 셀 자체가 느린 경우입니다. launch 플롭 edfxtp_1(구동력 1, enable mux 내장)의 clk→Q가 0.40ns이고, capture 쪽 library setup도 0.24ns로 큽니다. 플롭 관련 오버헤드만 0.64ns로 period 0.7ns의 91%입니다.
- `high_fanout` (low): a21o_4 출력이 fanout 7, cap 0.06으로 이 경로에서 가장 큰 부하이고 0.24ns가 걸립니다. 그 뒤에 툴이 삽입한 place174(buf_4)가 0.16ns를 더해 이 net에서만 0.40ns가 소모됩니다. 다만 전체 위반 1.65ns에 비하면 기여는 작습니다.

**PD 조치**
- edfxtp_1 플롭을 교체합니다. 예: enable을 앞단 mux로 분리하고 dfxtp_2/4를 사용하거나, 더 강한 enable 플롭이 라이브러리에 있으면 그것을 씁니다. clk→Q와 setup에서 0.1ns 안팎 절감이 기대됩니다(추정치).
- maj3_4(0.40ns)를 나눠서 바꾸거나 더 빠른 등가 로직(a21o/o21ai 조합)으로 재매핑합니다. repair_timing에 gate cloning이나 restructure 옵션을 적용하는 방식입니다.
- a21o_4의 fanout 7 net에서 critical sink를 분리합니다. critical 부하는 a21o_4가 직접 구동하게 하고, 나머지 부하만 place174 버퍼 뒤로 옮기면 0.1ns 안팎이 줄어듭니다.
- carry 체인 셀들을 critical path 기준으로 서로 붙여 배치합니다. 다만 현재 배선 지연이 0.00이라 개선 폭은 거의 없습니다.
- useful skew로 capture 클럭을 늦추는 방법이 있지만, 85개 endpoint가 모두 위반 중이라 다음 단(a_reg에서 출발하는 경로)에서 빌려올 여유가 없습니다. 0.05~0.1ns 이상은 기대하기 어렵습니다.
- 위 조치를 모두 합쳐도 약 0.3~0.5ns 개선이 한계로 추정되며, -1.65ns를 닫기에는 부족합니다.

**RTL/제약 조치**
- 클럭 주기를 0.7ns에서 2.35ns 이상(권장 약 2.5ns, 약 400MHz)으로 완화합니다. clock_min_period 2.35ns가 현재 구현에서 가능한 하한입니다.
- 0.7ns를 유지해야 한다면 뺄셈기와 mux 피드백 경로를 3~4단 이상 파이프라이닝해야 합니다. 플롭 오버헤드가 0.64ns라 단계당 게이트 1~2단밖에 허용되지 않으므로 사실상 비현실적입니다.
- 뺄셈기 구조를 바꿉니다. ripple-carry 대신 prefix 계열(Kogge-Stone/Brent-Kung)이나 carry-select를 쓰고, 합성 시 -abc 타이밍 최적화나 고속 adder 매핑을 강제합니다.
- GCD 알고리즘 수준에서 비교(a<b)와 뺄셈을 서로 다른 사이클로 분리하거나, 비교 결과를 미리 계산해 레지스터에 저장하는 방식으로 mux select 경로를 critical path에서 뺍니다.

**PD만으로 해결 가능?** 아니오

필요한 개선은 1.65ns로 period 0.7ns의 236%입니다. 경로를 보면 배선 0.00, skew -0.01로 PD가 다룰 수 있는 배선이나 클럭 쪽 요인이 거의 없고, 지연은 대부분 플롭 오버헤드(0.64ns)와 carry 체인 로직(1.27ns)에서 나옵니다. 조합 로직을 0으로 만들어도 플롭만으로 0.64ns가 필요하므로, 사이징과 버퍼링으로 얻을 수 있는 0.3~0.5ns(추정치)로는 닫을 수 없고 클럭 목표 조정이나 RTL 구조 변경이 필요합니다.

## dpath.b_reg.out[5]$_DFFE_PP_ → resp_msg[13] (slack -1.54)

**원인**
- `logic_depth` (high): logic_depth 11단, data_path_delay 2.10ns. 쓸 수 있는 시간은 required 0.85 - launch latency 0.29 = 0.56ns인데 데이터 경로가 약 3.75배입니다. 버퍼를 빼고 실제 연산 게이트만 보면 xor2(0.23), xnor2(0.17), nor4(0.29), o31ai(0.15), o211ai(0.18), xnor2(0.14)로 1.16ns입니다. 이는 뺄셈기의 group propagate/carry-lookahead 계열로 보이며, 이 경로도 Path 1과 같은 _119_ 블록을 지납니다.
- `slow_cell` (medium): nor4_1이 0.29ns로 이 경로의 조합 셀 중 가장 느립니다. 출력 slew도 0.31로 경로 최대인데, PMOS 4단 직렬 구조에 구동력 1이라 그렇습니다. 이 slew 때문에 다음 셀 o31ai_1의 지연도 커집니다. launch 플롭 edfxtp_1의 clk→Q도 0.43ns로 data path의 20%입니다.
- `other` (medium): 툴이 삽입한 버퍼 _119_/place220(0.17ns), _119_/rebuffer_mt287(0.15ns), place167(0.13ns)과 출력 포트 버퍼 output43(buf_1, 0.06ns)를 합치면 0.51ns로 data path의 24%입니다. place220과 place167은 fanout 1, cap 0.00으로 critical sink 하나만 구동하고 있습니다. 특히 place167(buf_4)이 output43(buf_1)을 혼자 구동하는 구조는 버퍼가 이중으로 들어간 중복으로 보입니다. 다만 다른 부하를 격리하려고 넣은 것일 수 있어 confidence는 medium입니다.
- `io_constraint` (low): output_external_delay는 0.14ns로 period의 20%라 주원인은 아닙니다. required 0.85를 역산하면 virtual clock 쪽에도 약 0.29ns의 latency가 적용된 것으로 보이며, 이 때문에 launch latency가 상쇄되고 있습니다(추정). io 제약을 0으로 해도 slack은 약 -1.40ns라 위반이 유지됩니다.

**PD 조치**
- 중복 버퍼 체인(place167 buf_4 → output43 buf_1)을 정리합니다. place167을 제거하거나 output 버퍼를 buf_2/4로 키워 하나로 합치면 약 0.1ns가 기대됩니다(추정치).
- place220과 rebuffer_mt287을 재검토합니다. 원래 driver(xnor2_2, o31ai_1)를 키우고 critical sink를 직접 구동하게 하면 버퍼 지연 0.15~0.17ns 중 일부를 회수할 수 있습니다.
- nor4_1을 nor4_2/4로 키우거나 nor2+nor2+and2 같은 2단 트리로 분해해 0.29ns 지연과 0.31 slew를 줄입니다. o31ai_1도 함께 키웁니다.
- edfxtp_1 launch 플롭의 clk→Q 0.43ns를 줄이기 위해 enable 분리와 구동력 높은 dfxtp로의 교체를 검토합니다.
- 출력 포트 근처로 경로 셀들을 배치합니다. 다만 배선 지연이 0.00이라 효과는 제한적입니다.
- 합계 약 0.3~0.5ns 개선이 예상되며(추정치), -1.54ns를 닫기에는 부족합니다.

**RTL/제약 조치**
- 클럭 주기를 2.35ns 이상(권장 약 2.5ns)으로 완화합니다. vclk_core_clock도 같은 주기를 따르도록 함께 조정합니다.
- resp_msg를 레지스터 출력으로 바꿉니다. 뺄셈기 결과를 출력 레지스터에 한 번 저장하면 io 경로가 clk→Q와 출력 버퍼(약 0.5ns)만 남아 io 경로 위반이 사라집니다. 대신 레이턴시가 1사이클 늘어납니다.
- output_external_delay 0.14ns와 virtual clock latency 설정이 실제 외부 인터페이스 사양에 맞는지 확인합니다. 영향은 작지만, 외부 모듈과의 실제 budget을 반영해야 합니다.
- 뺄셈기를 prefix adder로 바꾸는 구조 변경도 이 경로에 효과가 있습니다. Path 1과 같은 _119_ 블록이라 한 번 바꾸면 두 경로가 함께 개선됩니다.

**PD만으로 해결 가능?** 아니오

필요한 개선은 1.54ns로 period 0.7ns의 220%입니다. 배선 지연 0, io 제약 0.14ns로 PD나 제약으로 조정할 여지가 작습니다. 버퍼 정리와 사이징으로 회수할 수 있는 지연은 버퍼 0.51ns와 nor4 일부 정도이고, 이를 모두 제거해도 약 -1.0ns가 남습니다. clk→Q 0.43ns와 7단 연산 로직 1.16ns가 쓸 수 있는 시간 0.56ns를 훨씬 넘기 때문에, 출력 레지스터화나 클럭 목표 완화가 반드시 필요합니다.
