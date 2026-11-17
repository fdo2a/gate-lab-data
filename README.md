# gate-lab-data (시험)

발행 문지기 시험용 **보호된 자료 저장소**. 수집 코드(`collect.py`)·수집 작업(`.github/workflows/collect.yml`)·스냅샷(`snapshots/`)이
모두 이 저장소에 있고, 모든 가지와 태그가 보호 규칙으로 잠겨 있다(쓰기는 배포 열쇠만).

- `snapshots/<시장>/<날짜>/v<N>/` — 덧붙이기만 한다. `manifest.json` 에 파일마다 해시·출처·받은 시각, `index.json` 에 판 목록.
- 원천은 시험이라 운영 저장소의 그 날짜 커밋을 대역으로 쓴다(`source` 가 `standin:` 으로 시작). 국채 입찰만 TreasuryDirect 에서 직접 받는다.
