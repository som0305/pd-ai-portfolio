# AI 타이밍 분석: period_slow

- WNS: 0.0 / TNS: 0.0 / setup 위반: 0

## 전체 요약
slow corner(period_slow.rpt) finish 단계 기준으로 setup·hold·DRV(slew/cap/fanout) 위반은 하나도 없습니다(WNS=TNS=0, 위반 0건). 다만 여유가 아주 작습니다. 가장 나쁜 경로의 slack은 0.10ns로 주기 3.0ns의 3.3%이고, clock_min_period=2.9ns(fmax 344.8MHz)로 지금 목표 주기에서 0.1ns만 남아 있습니다. 공정·전압·온도(PVT) 변동, SI/crosstalk, 또는 ECO 한 번이면 바로 위반이 될 수 있는 수준이라 '닫혔다'기보다 '경계선에 걸쳐 있다'고 보는 게 맞습니다.

여유가 생긴 이유:
(1) launch·capture 클럭 latency가 둘 다 0.29ns로 같아서 skew가 0입니다. CTS가 균형을 잘 맞춰 skew로 잃은 시간이 없습니다.
(2) 리포트상 wire 지연 합이 0.00ns입니다. 배선 부담이 없는 작은 디자인으로 보입니다. 다만 소수 둘째 자리 반올림이나 기생 성분 반영 방식 때문일 수 있으니 SPEF가 실제로 반영됐는지 확인해야 합니다(confidence 낮음).
(3) 툴이 넣은 버퍼는 출력 경로의 place66 하나뿐입니다. 다시 말해 아직 써보지 않은 PD 최적화 여지가 남아 있습니다.

다음 병목:
1순위는 reg→reg 경로 b_reg[6]→b_reg[12]/DE(slack 0.10)입니다. 이 경로가 fmax를 결정합니다. 핵심은 _123_(o21bai_2)이 16개 enable 핀을 혼자 구동하는 high-fanout 넷이고, 이 넷의 slew 1.02ns가 셀 지연(0.79ns)과 capture flop의 setup(0.37ns)을 함께 키우고 있습니다.
2순위는 출력 경로 a_reg[4]→resp_msg[15](slack 0.15)입니다. output delay 0.6ns가 주기의 20%를 먹고, 9단 조합 로직에 약한 셀(or2_0, o311ai_1, xnor3_1)이 섞여 있습니다.

두 경로 모두 GCD 류 datapath의 비교기/감산기(_119_ 서브모듈, xor/xnor 체인)를 지나가므로 이 연산 블록이 공통 병목입니다. 현재 3.0ns 목표는 PD만으로 충분히 유지할 수 있습니다. 주기를 줄이려 할 때 PD만으로 기대할 수 있는 개선은 대략 0.3~0.5ns(약 2.5~2.6ns까지)로 추정하며, 그보다 더 줄이려면 RTL 구조 변경(enable 신호 미리 계산 후 레지스터, 출력 레지스터링)이 필요합니다.

## dpath.b_reg.out[6]$_DFFE_PP_ → dpath.b_reg.out[12]$_DFFE_PP_ (slack 0.1)

**원인**
- `high_fanout` (high): 마지막 단 _123_/Y(o21bai_2)의 fanout은 16, cap은 0.1pF로 다른 단(0.01~0.02pF)보다 5~10배 큽니다. 이 단의 지연 0.79ns는 data_path_delay 2.53ns의 31%이고, 출력 slew는 1.02ns입니다. endpoint가 edfxtp_1의 DE 핀이므로 b_reg 16비트 전체의 enable 넷으로 보입니다.
- `slow_cell` (medium): library_setup_time이 0.37ns로 큽니다. DE 핀에 들어오는 slew가 1.02ns라서 setup이 커진 것입니다(setup은 데이터 slew에 따라 달라짐). 또 xor2_1 출력 slew 0.34ns, xnor2_1 출력 slew 0.48ns로 X1 셀이 fanout 4~5를 구동하면서 각각 0.33ns, 0.30ns가 걸립니다. 런치 flop edfxtp_1의 clk→Q도 0.40ns입니다.
- `logic_depth` (medium): logic_depth는 8단입니다. 그중 _119_ 내부 xor/xnor/nor/aoi/oai 체인 6단(0.69→2.02ns, 1.33ns)은 비교기나 감산기의 carry/compare 체인으로 보입니다. 1단당 평균 0.22ns라 셀 자체는 크게 느리지 않고 단 수가 누적된 구조입니다.

**PD 조치**
- _123_ 출력 넷 버퍼링 또는 드라이버 복제: fanout 16을 2~4개 가지(buf_4/buf_8)로 나눕니다. slew를 1.02ns에서 0.2ns 안팎으로 낮추면 셀 지연은 약 0.3~0.4ns 줄고(버퍼 지연 포함), setup은 0.37ns에서 약 0.15ns로 줄어 합계 +0.3~0.5ns를 기대합니다(추정).
- _123_을 o21bai_4로 업사이징하거나, 같은 기능의 더 강한 셀로 리맵합니다.
- _119_/_132_ xor2_1→xor2_2, _119_/_134_ xnor2_1→xnor2_2로 업사이징해 slew 0.34/0.48ns를 낮춥니다. 단당 0.05~0.1ns 개선을 기대합니다.
- repair_timing -setup_margin(예: 0.2ns)을 주고 다시 돌려 이미 MET된 경로도 가드밴드를 확보하게 하고, set_max_transition을 0.5ns 정도로 조여 slew 1.02ns 넷이 자동으로 수리되게 합니다.
- useful skew는 효과가 제한적입니다: launch와 capture가 같은 b_reg 그룹이라 그룹 전체 latency를 옮기면 상쇄됩니다. 개별 flop(b_reg[12])의 capture만 늦추는 건 가능하지만, b_reg[12]에서 나가는 경로의 여유를 먼저 확인해야 합니다.

**RTL/제약 조치**
- b_reg enable(_123_, 비교 결과에서 만든 swap/load 조건)을 한 사이클 앞서 계산해 레지스터에 담으면, 비교기 체인과 enable 팬아웃 넷이 분리됩니다.
- enable flop(edfxtp) 대신 일반 DFF + 앞단 MUX 구조로 합성하거나, 비교기를 carry-lookahead/병렬 비교 구조로 바꿔 depth 8을 줄입니다.
- 합성 단계에서 clock 목표를 조금 더 빡빡하게(예: 2.7ns) 주고 set_max_fanout(예: 8)을 걸어 ABC가 더 얕은 구조를 고르게 합니다.
- sign-off 마진 정책(OCV/uncertainty)에 비해 0.1ns가 충분한지 검토하고, 부족하면 주기를 3.1~3.2ns로 완화하는 것도 고려합니다.

**PD만으로 해결 가능?** 예

현재 MET(slack +0.10ns)입니다. 주기 3.0ns, skew 0, wire 0이므로 여유가 작은 원인은 전부 셀 지연(2.53ns)과 setup(0.37ns)입니다. 그중 단일 high-fanout 넷 하나가 지연 0.79ns를 만들고 setup까지 부풀린 상태라 PD 조치(버퍼링/업사이징)로 회수할 수 있는 양이 큽니다(0.3~0.5ns 추정). 그래서 3.0ns 유지는 물론 약 2.5~2.6ns까지도 PD만으로 가능해 보입니다. 그보다 더 공격적인 목표는 비교기 체인 depth 때문에 RTL 변경이 필요합니다. 참고로 required 2.91 ≈ 3.0+0.29−0.37이 맞아떨어지므로 clock uncertainty가 거의 없는 설정으로 보이며, 실제 sign-off 마진을 넣으면 위반으로 바뀔 수 있습니다.

## dpath.a_reg.out[4]$_DFFE_PP_ → resp_msg[15] (slack 0.15)

**원인**
- `io_constraint` (high): output_external_delay가 0.6ns로 주기 3.0ns의 20%를 외부 몫으로 뺍니다. required는 2.69ns(=3.0+0.29−0.6, vclk 쪽에도 latency 0.29가 반영된 것으로 보임)입니다. reg→reg 경로의 required 2.91보다 0.22ns 빡빡합니다.
- `logic_depth` (medium): 레지스터에서 출력 포트까지 조합 로직만으로 9단, data_path_delay 2.25ns입니다. resp_msg가 flop을 거치지 않고 _119_ 연산 결과(xnor2 _131_ → output45)에서 바로 나갑니다.
- `slow_cell` (medium): xnor3_1 0.45ns(fanout 5), o311ai_1 0.38ns(fanout 1, cap 0.01인데 slew 0.38 — PMOS 3단 직렬이라 약함), or2_0 0.29ns(가장 약한 or2_0 사이즈)입니다. 이 세 셀의 합 1.12ns가 data path의 50%입니다.
- `other` (low): 툴이 넣은 버퍼 _119_/place66(buf_4)의 지연이 0.17ns인데, 구동 부하는 fanout 3, cap 0.01pF로 작습니다. 타이밍보다는 배치/DRV 목적으로 들어간 것으로 보이며, 이 경로 입장에서는 순수한 추가 지연일 수 있습니다(추정).

**PD 조치**
- or2_0을 or2_2로, o311ai_1을 o311ai_2로, xnor3_1을 xnor3_2로 업사이징합니다(또는 xnor3를 xnor2 두 개로 분해). 합계 0.2~0.3ns 개선을 기대합니다(추정).
- place66 버퍼를 제거하거나 사이즈를 줄인 뒤 다시 평가합니다(remove_buffers 후 repair_timing). 해당 넷 부하가 0.01pF라 버퍼 없이도 slew 문제가 없을 가능성이 높습니다.
- _119_/_131_와 output45를 resp_msg[15] IO 핀 가까이 배치합니다(set_dont_touch를 걸지 않은 상태에서 timing-driven placement 가중치를 높임).
- useful skew: a_reg의 clock latency를 조금 앞당기면(launch를 이르게) 출력 경로 slack이 늘어납니다. 단, a_reg가 capture하는 다른 reg→reg 경로의 setup이 그만큼 줄어드니 먼저 확인해야 합니다.

**RTL/제약 조치**
- resp_msg를 출력 레지스터로 받도록 RTL을 바꿉니다. 그러면 출력 경로가 clk→Q(~0.4ns)+출력 버퍼만 남아 slack이 약 1.5ns 이상 생깁니다(대신 레이턴시 1사이클 증가).
- output delay 0.6ns가 실제 외부 인터페이스 예산인지 SoC/보드 측과 다시 확인합니다. 보수적으로 잡은 값이면 완화합니다.
- 합성 시 출력 경로에도 같은 IO 제약을 줘서 ABC가 xnor3/or2_0 같은 느린 매핑을 피하게 합니다.

**PD만으로 해결 가능?** 예

현재 MET(slack +0.15ns)입니다. 지연의 절반이 약한 사이즈 셀 3개에 몰려 있고 타이밍에 불리한 버퍼도 하나 있어 PD 업사이징만으로 0.2~0.4ns를 더 확보할 수 있다고 봅니다. 다만 주기를 줄이면 output delay 0.6ns가 고정 비율 또는 절대값으로 남아 이 경로가 1순위 병목이 될 수 있습니다. 근본 대책은 출력 레지스터링(RTL)이나 IO 제약 재검토입니다. vclk_core_clock의 period_min이 0.0(fmax inf)인 것은 vclk가 reg→reg 경로 없이 IO 전용 가상 클럭이기 때문이며 정상입니다.
