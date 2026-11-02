# AI 타이밍 분석: period_hmmm

- WNS: 0.0 / TNS: 0.0 / setup 위반: 0

## 전체 요약
위반 없음. setup 위반 0건, hold 위반 0건, slew/cap/fanout DRV도 0건이고 WNS·TNS 모두 0이다. 다만 worst slack이 +0.03ns로, 2.5ns 주기의 1.2%밖에 남지 않았다. clock_min_period가 2.47ns(405MHz)이므로 주기 2.5ns는 사실상 fmax에 맞닿아 있다. 여유가 '생긴' 것이 아니라 repair_timing이 겨우 0을 넘긴 상태로 보는 게 맞다. reg2reg(core_clock)와 출력(vclk_core_clock), 서로 다른 path group 두 개가 똑같이 +0.03이다. 그래서 주기를 줄이거나 IO budget(clk_io_pct=0.2 → output delay 0.5ns)을 늘리면 두 경로가 동시에 위반으로 넘어간다. 두 경로 공통점: (1) wire delay 합이 0.00ns이고 셀 지연만 있다. 작은 GCD 디자인이라 배선은 문제가 아니다. (2) edfxtp_1(enable 내장 플롭)의 clk→Q가 0.39ns이고, reg2reg 경로에서는 setup 0.24ns까지 더해 0.63ns(주기의 25%)를 플롭이 쓴다. (3) 툴이 넣은 버퍼가 경로 지연의 22~30%를 차지한다(경로1 0.66/2.22ns, 경로2 0.49/1.97ns). (4) _119_ 계층(감산기/비교기로 추정)의 리플형 XOR/AOI 체인이 logic depth 11~12단을 만든다. SDC 확인 결과 core_clock과 vclk 모두 set_clock_latency 0.29가 걸려 있어 skew는 0이다. 출력 경로 required 2.29 = 2.5 + 0.29 − 0.5로 일치한다. 다음 병목: 경로1(a_reg[3]→a_reg[6])이 fmax를 결정한다. 출력 경로(b_reg[2]→resp_msg[12])는 IO 제약 비율에 같은 정도로 민감하다. 출력 포트 cap이 0.00으로 나와 set_load가 없는 것으로 보이며, 실제 부하가 붙으면 출력 경로가 먼저 깨질 가능성이 있다.

## dpath.a_reg.out[3]$_DFFE_PP_ → dpath.a_reg.out[6]$_DFFE_PP_ (slack 0.03)

**원인**
- `logic_depth` (high): logic depth는 12단, data path는 2.22ns다. 경로는 xnor3(0.40) → o21ai(0.11) → a221oi(0.35) → xor2(0.06) → mux2i(0.17) → o21ai(0.08)로 이어진다. 이는 a−b 감산 carry/비교 체인 뒤에 a_reg 입력 mux가 붙은 전형적인 리플 구조다. 비트 3에서 비트 6으로 전파되는 carry 경로라는 점도 이 해석과 맞는다. 순수 로직 셀(버퍼·플롭 제외)만 합쳐도 1.17ns다.
- `other` (medium): 툴 삽입 버퍼(place143 0.14, place114 0.17, rebuffer_mt173 0.14, rebuffer_mt172 0.10, place111 0.11)가 합계 0.66ns로 data path의 30%를 차지한다. 특히 rebuffer_mt173 → mt172 → place111 3단 체인은 0.35ns를 쓴다. 그런데 이 체인의 fanout은 2/1/1이고 cap은 0.01/0.00/0.00ns 수준이다. 경로상 부하가 거의 없으므로, critical 경로 입장에서는 off-path 부하를 분리하려고 넣은 버퍼의 지연을 그대로 떠안고 있을 가능성이 크다. 버퍼링 구조가 최적이 아니라는 추정이라 confidence는 medium이다.
- `slow_cell` (medium): a221oi_1은 fanout 1, cap 0.01인데 delay가 0.35ns이고 출력 slew가 0.30으로 경로 최대다. 직렬 PMOS 스택이 있는 약한 1x AOI라서 그렇다. xnor3_1은 0.40ns로 단일 셀 최대 지연이다. 시작 플롭 edfxtp_1은 clk→Q 0.39ns에 library setup 0.24ns까지 더해 0.63ns를 플롭이 쓴다. 일반 dfxtp에 비해 setup이 큰 것은 enable mux가 내장된 플롭이기 때문이다.
- `long_wire` (high): 반증이다. wire_delay_sum이 0.00, wire_delay_ratio가 0.0이고, 모든 입력핀 delay가 0.00이다. 배선은 원인이 아니다.
- `clock_skew` (high): 반증이다. launch와 capture latency가 모두 0.29이고 skew는 0.00이다. SDC의 set_clock_latency 0.290과 일치한다.

**PD 조치**
- rebuffer_mt173 → mt172 → place111 3단 체인(0.35ns)을 정리한다. critical sink는 원 드라이버(xor2 _223_)에 직접 붙이고, off-path 부하만 버퍼로 분리한다. 1~2단을 줄이면 약 0.1~0.25ns를 회수할 수 있을 것으로 추정한다.
- a221oi_1 → a221oi_2/_4로 업사이징한다. 출력 slew 0.30이 개선되면 place114의 입력 slew도 좋아져 0.1ns 내외 개선이 예상된다.
- xnor3_1(0.40ns)을 xnor3_2/_4로 업사이징하거나, xnor2+xor2로 분해한 뒤 critical 입력을 늦게 도착하는 핀에 배정한다(pin swap).
- repair_timing에 -setup_margin을 주고 반복 횟수를 늘린다. 버퍼 제거(remove_buffers 후 재합성)를 시도하고 sizing을 우선하도록 설정한다.
- useful skew는 효과가 제한적이다. launch와 capture가 모두 a_reg 뱅크라서 a_reg[6] capture를 늦추면 a_reg[6] 출발 경로가 그만큼 손해를 본다. CTS 단계에서 비트별 latency 미세 조정 정도만 기대할 수 있다.

**RTL/제약 조치**
- GCD 감산기/비교기(_119_)를 리플 구조에서 carry-lookahead/prefix 구조로 바꾸거나, synth에서 ABC 스크립트를 delay 목표(ABC_AREA=0, 타이밍 우선)로 돌려 logic depth를 줄인다.
- enable 플롭(edfxtp)의 setup 0.24와 clk→Q 0.39 부담을 줄인다. enable을 dfxtp 앞 mux로 풀거나, 클럭 게이팅 방식으로 바꾸는 것을 검토한다.
- 더 높은 주파수가 목표라면 감산과 비교/선택 사이를 파이프라이닝한다. 다만 GCD FSM의 반복 의존성 때문에 사이클 수가 늘어난다.
- 현재 주기 2.5ns는 min period 2.47ns에 거의 붙어 있다. 사인오프 마진(OCV, uncertainty)을 고려하면 2.6~2.7ns로 완화하는 것이 현실적이다.

**PD만으로 해결 가능?** 예

이미 MET 상태이므로 PD만으로 닫혀 있다. 경로는 2.5ns 주기 + 0.29 capture latency − 0.24 setup ≈ 2.54 required, arrival 2.51로 slack +0.03이다. 이 경로가 fmax 405MHz(2.47ns)를 결정하는 critical 경로다. wire 기여가 0이므로 배치 조정으로 얻을 것은 거의 없다. 회수 여지는 버퍼 체인 정리와 약한 1x 셀 업사이징에 있으며, 추정 0.2~0.4ns다. 따라서 주기를 2.2~2.3ns 정도까지 줄이는 것은 PD로 가능해 보인다. 그 이하로 가려면 12단 리플 구조와 enable 플롭 오버헤드(0.63ns) 때문에 RTL/합성 구조 변경이 필요하다는 추정이다.

## dpath.b_reg.out[2]$_DFFE_PP_ → resp_msg[12] (slack 0.03)

**원인**
- `io_constraint` (high): output delay가 0.5ns(=2.5 × clk_io_pct 0.2)로 주기의 20%를 외부에 할당한다. required 2.29 = 2.5 + 0.29(vclk latency) − 0.5다. vclk에도 set_clock_latency 0.29가 걸려 있어 capture 쪽이 0.29를 보상받는다. 만약 실제 외부 수신단에 이 latency 보상이 없다면 slack은 약 −0.26ns가 된다. 출력 포트 cap이 0.00이고 output42(buf_1)가 0.10ns이므로 set_load가 없는 것으로 보인다. 실제 패드나 외부 부하가 붙으면 buf_1 지연이 크게 늘어난다.
- `logic_depth` (high): logic depth 11단, data path 1.97ns다. 체인은 xor2(0.17) → xnor2_2(0.14) → nor2(0.06) → a21oi(0.27) → o221ai(0.17) → xnor2(0.18)다. 이는 b_reg에서 시작하는 감산기 출력이 그대로 resp_msg 포트로 나가는 조합 출력 경로다. resp_msg가 a−b 결과를 레지스터 없이 바로 내보내는 구조로 추정된다.
- `other` (medium): 삽입 버퍼 place153 0.17, place142 0.14, rebuffer_mt180 0.18이 합계 0.49ns로 data path의 25%다. 여기에 출력 포트 버퍼 output42(buf_1) 0.10까지 더하면 0.59ns다. rebuffer_mt180은 fanout 1, cap 0.01인데 0.18ns를 쓴다. 이 값만 보면 이 버퍼가 꼭 필요한지 의문이다.
- `slow_cell` (medium): a21oi_1은 fanout 3에서 0.27ns이고 출력 slew 0.30으로 경로 최대다. 1x 셀이 fanout 3을 직접 구동하는 것이 원인이다. 시작 플롭 edfxtp_1의 clk→Q는 0.39ns다.
- `long_wire` (high): 반증이다. wire_delay_sum 0.00으로 배선 기여가 없다.

**PD 조치**
- a21oi_1(fanout 3, slew 0.30)을 a21oi_2/_4로 업사이징한다. 그러면 뒷단 o221ai의 입력 slew도 함께 개선된다.
- rebuffer_mt180(fanout 1, 0.18ns)과 place142(fanout 1, 0.14ns)가 critical 경로에 꼭 필요한지 재검토한다. 제거하거나 off-path로 이동시킨다.
- 출력 포트 버퍼 output42를 buf_1에서 buf_2/_4로 업사이징한다. 실제 set_load를 넣으면 반드시 필요해진다.
- b_reg와 출력 로직을 출력 핀 쪽에 가깝게 배치한다. 현재는 wire가 0이라 효과가 작지만, 실제 부하와 RC가 반영되면 의미가 생긴다.
- useful skew로 b_reg launch latency를 앞당길 수 있다. 다만 b_reg로 들어오는 경로의 setup이 그만큼 손해를 보므로 trade-off를 확인해야 한다.

**RTL/제약 조치**
- resp_msg를 레지스터 출력으로 바꾼다(registered output). 이렇게 하면 IO 경로가 clk→Q + 출력 버퍼만 남아 문제가 근본적으로 사라진다. 대신 응답 지연이 1사이클 늘어난다.
- SDC 검증: vclk의 set_clock_latency 0.29가 실제 보드나 상위 레벨 환경을 반영하는지 확인한다. 반영하지 않는다면 이 경로는 실제로 −0.26ns 위반이다.
- 출력 포트에 현실적인 set_load와 set_driving_cell을 추가해 IO 경로를 재평가한다.
- clk_io_pct 0.2가 상위 블록과 합의된 budget인지 확인한다. 상향 시 즉시 위반, 하향 시 여유가 생긴다.

**PD만으로 해결 가능?** 예

현재 제약에서는 MET(+0.03)이다. 하지만 이 결과는 SDC의 IO budget(0.5ns)과 vclk latency 보상(0.29) 가정에 전적으로 의존한다. PD로 회수 가능한 몫은 a21oi 업사이징과 불필요 버퍼 2개 정리로, 추정 0.2~0.35ns다. 출력 포트 cap이 0.00이라 실제 부하를 넣으면 output42 지연이 늘어나므로, 현재 slack은 낙관적인 값으로 봐야 한다. 제약이 현실화되면(set_load 추가, vclk latency 제거) PD만으로는 부족하다. 그 경우 registered output 같은 RTL 변경이 가장 확실한 해법이다.
