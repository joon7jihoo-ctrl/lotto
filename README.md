# 🎯 Lotto Grid AI Analyzer

> **로또 번호 분석 & 추천 데스크톱 애플리케이션**  
> 동행복권 당첨 이력을 7×7 공간 격자 분석 엔진으로 처리하는 PyQt6 기반 AI 보조 도구

<br>

## ⚠️ 면책 고지

**로또는 독립 시행 난수 추첨입니다.**  
본 프로그램의 "확률 점수"는 당첨 보장이 아닌 **통계·휴리스틱 우선순위 점수**입니다.  
분석 결과를 재미와 학습 목적으로만 활용하시기 바랍니다.

<br>

## ✨ 주요 기능

| 기능 | 설명 |
|------|------|
| **자동 데이터 갱신** | 동행복권 API → SQLite 캐시 → Excel → 내장 데모의 4단계 자동 폴백 |
| **8단계 레이어 분석** | 빈도·미출수·직전사각수·데드존·가중치 매트릭스 복합 분석 |
| **7×7 격자 시각화** | 1~45번을 7×7 공간에 매핑한 히트맵 & 격자 뷰 |
| **조합 생성 필터** | 합계 범위·홀짝·고저·연번·AC값 5중 수학 필터 |
| **인기 패턴 회피** | 생일수·연속수·끝수 몰림·등차 패턴 감지로 배당 분산 최소화 |
| **이월수 믹서** | 직전 회차 번호와 예상수를 사용자 설정 비율로 블렌딩 |
| **롤링 백테스트** | 현재 알고리즘 vs 무작위 기준선 성능 자동 비교 |
| **SQLite 이력 저장** | 생성한 모든 조합을 타임스탬프와 함께 영구 보관 |
| **다크 테마 UI** | PyQt6 기반 커스텀 다크 테마 + Matplotlib 시각화 |

<br>

## 🖥️ 스크린샷

> *앱 실행 후 스크린샷을 추가 예정*

<br>

## 📁 프로젝트 구조

```
lotto/
├── lotto_grid_ai_pyqt6.py           # 단일파일 실행 버전 (Ver1)
├── lotto_history.xlsx               # 로컬 당첨 이력 (선택 사항)
├── requirements_lotto_grid_ai.txt   # 의존성
│
└── GRID/
    ├── Ver1.0/                      # 1차 모듈화 버전
    │   └── lotto_grid_ai/
    │
    └── Ver2.0/                      # ✅ 최신 권장 버전
        ├── lotto_grid_ai_pyqt6_v2.py   # 실행 진입점
        └── lotto_grid_ai/
            ├── app.py          # 애플리케이션 진입점
            ├── models.py       # 데이터 클래스 & 상수
            ├── grid.py         # 7×7 격자 좌표 변환
            ├── analysis.py     # Layer 2~7 분석 엔진
            ├── generation.py   # 조합 생성 & 필터
            ├── storage.py      # SQLite 저장소 & 데이터 로더
            ├── controller.py   # MVC 컨트롤러
            ├── ui.py           # PyQt6 뷰
            ├── theme.py        # 다크 테마 스타일시트
            └── utils.py        # 공통 유틸리티
```

<br>

## 🚀 빠른 시작

### 1. 의존성 설치

```bash
pip install -r requirements_lotto_grid_ai.txt
```

의존성 목록:
```
PyQt6>=6.6
pandas>=2.0
numpy>=1.24
matplotlib>=3.8
seaborn>=0.13
requests>=2.31
```

### 2. 실행

**최신 Ver2.0 (권장)**
```bash
cd GRID/Ver2.0
python lotto_grid_ai_pyqt6_v2.py
```

**단일파일 버전 (Ver1)**
```bash
python lotto_grid_ai_pyqt6.py
```

<br>

## 🧮 분석 알고리즘

### 레이어 구조

```
Layer 1  ──  데이터 로드 (API → 캐시 → 데모)
Layer 2A ──  기간별 빈도 분석 (5/10/20/50/100회 가중치)
Layer 2B ──  장기 미출수 추적
Layer 3  ──  직전사각수 (7×7 격자 8방향 인접 탐색)
Layer 4  ──  완전사각/데드존 탐지
Layer 5  ──  종합 가중치 매트릭스 (0~100점)
Layer 7  ──  이전 당첨 + 예상수 믹서
Layer 8+ ──  수학 검증 필터 + 조합 생성
```

### 7×7 격자 매핑

```
 1  2  3  4  5  6  7
 8  9 10 11 12 13 14
15 16 17 18 19 20 21
22 23 24 25 26 27 28
29 30 31 32 33 34 35
36 37 38 39 40 41 42
43 44 45  ·  ·  ·  ·
```

**직전사각수**: 직전 회차 당첨 번호의 8방향 인접 번호를 다음 회차 후보로 가중치 부여

### 수학 검증 필터 (Layer 8)

| 필터 | 조건 |
|------|------|
| 합계 범위 | 100 ≤ Σ ≤ 170 |
| 홀짝 균형 | 홀수 2~4개 (3:3, 2:4, 4:2) |
| 고저 균형 | 고번호(23~45) 2~4개 |
| 연번 제한 | 최대 2연속 허용 |
| AC값 | ≥ 7 (조합 복잡도) |

### AC값 (Arithmetic Complexity)

```
AC = (서로 다른 쌍의 차이 수) - (선택 번호 수 - 1)
```
6개 번호 기준 범위: 0~10. 높을수록 다양한 조합.

<br>

## ⚙️ 주요 설정값

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `top_candidate_count` | 20 | 후보 번호 풀 크기 |
| `output_limit` | 30 | 생성할 조합 수 |
| `mix_previous_ratio` | 10% | 이월수 믹스 비율 |
| `recent_weight` | 55 | 빈도 점수 가중치 |
| `missing_weight` | 25 | 미출수 점수 가중치 |
| `deadzone_weight` | 5 | 데드존 점수 가중치 |
| `max_overlap` | 4 | 조합 간 최대 겹침 수 |
| `backtest_rounds` | 80 | 롤링 백테스트 회차 수 |

<br>

## 🗄️ 데이터 관리

### 자동 데이터 소스 우선순위

1. **동행복권 API** (`dhlottery.co.kr`) — 네트워크 정상 시 최신 회차 자동 갱신
2. **SQLite 캐시** — 로컬 `lotto_history.db` 증분 업데이트
3. **Excel 파일** — `lotto_history.xlsx` 수동 갱신 지원
4. **내장 데모 데이터** — 오프라인 환경에서도 UI/알고리즘 검증 가능

### SQLite 스키마

```sql
-- 당첨 이력
CREATE TABLE lotto_draws (
    draw_no INTEGER PRIMARY KEY,
    date TEXT, n1~n6 INTEGER, bonus INTEGER, updated_at TEXT
);

-- 생성된 조합 이력
CREATE TABLE generated_combinations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT, source_draw_no INTEGER,
    n1~n6 INTEGER, total INTEGER,
    odd_count INTEGER, high_count INTEGER,
    ac_value INTEGER, carry_count INTEGER,
    score REAL, pattern_risk INTEGER, pattern_notes TEXT
);
```

<br>

## 🔧 개발 환경

- **Python** 3.10+
- **PyQt6** 6.6+
- **OS** Windows / macOS / Linux (Qt 지원 환경)

<br>

## 📊 버전 이력

| 버전 | 변경사항 |
|------|----------|
| **Ver2.0** | BacktestSummary 추가, 인기 패턴 회피(pattern_risk), SQLite 마이그레이션 지원 |
| **Ver1.0** | MVC 패키지 구조로 분리, SQLite 영속화 |
| **초기** | 단일 파일 프로토타입 (lotto_grid_ai_pyqt6.py) |

<br>

## 🤝 기여 방법

1. 이 저장소를 Fork하세요
2. 기능 브랜치를 생성하세요 (`git checkout -b feature/새기능`)
3. 변경사항을 커밋하세요 (`git commit -m 'feat: 새기능 추가'`)
4. 브랜치에 Push하세요 (`git push origin feature/새기능`)
5. Pull Request를 생성하세요

<br>

## 📄 라이선스

이 프로젝트는 MIT 라이선스를 따릅니다.

---

> **Note**: 본 소프트웨어는 교육·분석 목적으로 제작되었습니다. 로또 당첨을 보장하지 않으며, 도박 목적으로의 사용을 권장하지 않습니다.
