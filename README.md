# SMTM 암호화폐 자동거래 시스템

SMTM(Show Me The Money)은 `crypto_auto_trading_system_design_v1.0.docx` 설계서를 기반으로 만든 암호화폐 자동거래 시스템 MVP입니다.

현재 버전은 실제 주문 전송보다 안전한 검증 흐름에 초점을 둡니다. 파일 기반 시뮬레이션, Upbit 공개 시세 조회, 전략/리스크/체결/분석 모듈, 로컬 대시보드를 통해 자동거래 시스템의 전체 흐름을 확인할 수 있습니다.

## 주요 기능

- CSV 파일 및 Upbit 공개 캔들 데이터 기반 데이터 공급자
- 교체 가능한 전략 인터페이스와 SMA 교차 전략
- 주문 전 리스크 검사 및 킬 스위치
- 수수료, 슬리피지, 부분 체결을 반영한 시뮬레이션 트레이더
- 감사 이벤트, 잔고 스냅샷, 수익률 리포트, JSON/CSV 출력
- SQLite 기반 감사/복구용 저장소
- 단일 시뮬레이션, 대량 시뮬레이션, 라이브 드라이런 CLI
- 브라우저에서 실행 결과와 진행 상황을 확인하는 한글 대시보드
- 비트코인과 엑스알피(리플) 실시간 가격 차트 및 거래량 막대
- 차트 hover 시 시간, 가격, 거래량 tooltip 표시
- 브라우저 F5 새로고침 후에도 실행/중지 상태와 누적 차트 데이터 유지

## 안전 안내

이 프로젝트는 자동거래 시스템의 구조와 동작을 검증하기 위한 엔지니어링 소프트웨어입니다. 투자 조언이 아니며, 현재 MVP에서는 실제 거래소 주문 전송을 활성화하지 않습니다.

`live-dry-run` 명령은 Upbit 공개 시세 API만 호출합니다. 주문은 실제 거래소 계정으로 전송되지 않고 이벤트로만 기록됩니다.

## 빠른 시작

```powershell
python -m pip install -e .
python -m unittest discover -s tests
smtm simulate --config configs/simulation.example.json --output reports/sample_report.json
```

패키지 설치 없이 실행하려면 `PYTHONPATH`를 지정합니다.

```powershell
$env:PYTHONPATH="src"
python -m smtm.cli simulate --config configs/simulation.example.json --output reports/sample_report.json
```

## 로컬 대시보드 실행

```powershell
$env:PYTHONPATH="src"
python -m smtm.cli ui --host 127.0.0.1 --port 8765
```

또는 Windows에서 간단히 실행할 수 있습니다.

```powershell
python run_ui.py
```

브라우저에서 아래 주소를 엽니다.

```text
http://127.0.0.1:8765
```

대시보드에서 `시작`을 누르면 시뮬레이션과 실시간 시세 갱신이 시작됩니다. `중지`를 누르기 전까지 데이터가 계속 업데이트되며, 실행 중에는 `시작` 버튼이 비활성화됩니다. 시작 전이나 중지 후에는 `중지` 버튼이 비활성화됩니다.

## 대시보드 화면

대시보드는 다음 정보를 한글로 표시합니다.

- 시뮬레이션 진행 상태와 누적 틱 수
- 현재 자산, 누적 수익률, 최대 낙폭
- 주문 수, 체결 수, 거절 수
- 최근 체결 내역과 감사 이벤트
- 자산 곡선
- 비트코인 실시간 차트
- 엑스알피(리플) 실시간 차트

실시간 차트는 처음 로드할 때 최근 1시간 분봉 데이터를 불러와 표시합니다. 이후에는 실시간 시세를 누적해 선 차트로 보여주며, 같은 차트 안에 거래량을 막대 그래프로 함께 표시합니다.

차트에 마우스를 올리면 가장 가까운 시점의 시간, 가격, 거래량이 tooltip으로 표시됩니다.

## 새로고침 동작

브라우저에서 F5를 누르거나 페이지를 새로고침해도 마지막 대시보드 상태를 복원합니다.

- 실행 중이면 실행 중 상태와 버튼 상태를 유지합니다.
- 중지 상태이면 중지 상태와 버튼 상태를 유지합니다.
- BTC/XRP 실시간 차트와 자산 곡선의 누적 데이터를 다시 표시합니다.
- 서버가 살아 있으면 복원 직후 최신 실행 상태와 시세로 다시 갱신합니다.

## 라이브 드라이런

```powershell
smtm live-dry-run --config configs/live.dry-run.example.json --ticks 3
```

이 명령은 공개 시세만 조회합니다. 인증 주문이나 실제 매매는 수행하지 않습니다.

## 대량 시뮬레이션

```powershell
smtm mass-simulate --config configs/simulation.example.json --output reports/mass_summary.json
```

여러 구간 또는 설정을 이용해 반복 시뮬레이션을 수행하고 요약 리포트를 생성할 수 있습니다.

## 프로젝트 구조

- `src/smtm/models.py`: 공통 데이터 모델
- `src/smtm/data_provider.py`: 파일 및 Upbit 캔들 데이터 공급자
- `src/smtm/strategies.py`: 전략 구현
- `src/smtm/risk.py`: 주문 리스크 검사와 킬 스위치
- `src/smtm/trader.py`: 가상 시장, 시뮬레이션 체결, 드라이런 트레이더
- `src/smtm/analyzer.py`: 이벤트 저장과 성과 리포트
- `src/smtm/repository.py`: SQLite 저장소
- `src/smtm/operator.py`: 자동거래 실행 오케스트레이션
- `src/smtm/mass_simulator.py`: 대량 시뮬레이션 실행기
- `src/smtm/ui.py`: 로컬 웹 대시보드 서버
- `src/smtm/web/`: 대시보드 HTML, CSS, JavaScript
- `src/smtm/cli.py`: 명령행 인터페이스
- `tests/`: 단위 테스트

## 리포트와 산출물

시뮬레이션 리포트는 기본적으로 `reports/` 아래에 생성됩니다. 실행 결과 JSON, CSV, SQLite, 로그 파일은 `.gitignore`에 의해 Git 추적에서 제외됩니다. 저장소에는 `reports/.gitkeep`만 포함해 디렉터리 구조를 유지합니다.

## 개발 검증

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

프론트엔드 JavaScript 문법 확인:

```powershell
node --check src/smtm/web/app.js
```
