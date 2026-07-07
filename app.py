import streamlit as st
import google.generativeai as genai

st.set_page_config(
    page_title="데이터 분석 프롬프트 생성기",
    page_icon="🔍",
    layout="centered"
)

# --- API 키 로드 ---
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    st.error("API 키가 설정되지 않았습니다. .streamlit/secrets.toml을 확인해주세요.")
    st.stop()

genai.configure(api_key=api_key)

# --- 세션 상태 초기화 ---
DEFAULTS = {
    "natural_input": "",
    "target_ai": "Claude",
    # Claude 필드 (RCDO)
    "role": "",
    "context": "",
    "data_desc": "",
    "data_paste": "",
    "priority": "",
    "audience": "",
    "output_format": "",
    "output_types": [],
    # Gemini 필드
    "g_role": "",
    "g_background": "",
    "g_data_schema": "",
    "g_requests": "",
    "g_output_format": "",
}
for key, val in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = val


def clear_all():
    for key, val in DEFAULTS.items():
        st.session_state[key] = val


def fill_example():
    st.session_state["role"] = "CS팀 주간 보고 담당자"
    st.session_state["context"] = "4월 한 달간 고객 상담 데이터를 분석해서 팀장 주간 보고용 요약 자료를 만들어야 합니다. 채널별 현황과 주요 이슈를 파악하는 것이 목표입니다."
    st.session_state["data_desc"] = "4월 고객 상담 로그 551건 (CSV) — 컬럼: 상담일자, 채널(전화/채팅/이메일), 카테고리(반품/배송/결제/기타), 처리시간(분), 만족도(1~5점)"
    st.session_state["output_format"] = "채널별 상담 건수 표 + 카테고리별 TOP3 이슈 + 평균 처리시간 비교 + 이번 달 특이사항 2~3가지"
    st.session_state["priority"] = "반복 민원 패턴 파악이 최우선, 전월 대비 증감 추이 포함"
    st.session_state["audience"] = "팀장 보고용 — 핵심 수치 위주, 기술적 세부사항 최소화"
    st.session_state["output_types"] = ["📊 표 (Table)", "📝 마크다운 헤더/섹션"]


def fill_example_gemini():
    st.session_state["g_role"] = "고객 서비스 데이터를 분석하는 5년 차 시니어 데이터 분석가"
    st.session_state["g_background"] = (
        "우리 서비스는 최근 이메일 채널에서 재문의율이 높아지는 문제를 겪고 있어. "
        "이번 분석의 목적은 어떤 고객군에서 재문의가 집중되는지 데이터로 파악하고 "
        "개선 우선순위를 결정하는 거야."
    )
    st.session_state["g_data_schema"] = (
        "- customer_id: 고객 고유 ID (String)\n"
        "- channel: 상담 채널 (전화/채팅/이메일)\n"
        "- category: 문의 카테고리 (반품/배송/결제/기타)\n"
        "- recontact_yn: 재문의 여부 (Y/N)\n"
        "- satisfaction: 만족도 점수 (1~5점)\n"
        "- grade: 고객 등급 (VIP/일반/신규)"
    )
    st.session_state["g_requests"] = (
        "1. 채널별 재문의율(recontact_yn=Y 비율)을 계산하고, 가장 높은 채널과 낮은 채널을 비교해줘.\n"
        "2. 재문의가 발생한 고객과 그렇지 않은 고객의 만족도 평균을 등급별로 분석해줘.\n"
        "3. 분석 결과를 바탕으로 현업에서 바로 적용할 수 있는 개선 아이디어 3가지를 제안해줘."
    )
    st.session_state["g_output_format"] = (
        "- 채널별 재문의율 비교는 표(테이블) 형태로 출력할 것\n"
        "- 분석 과정의 핵심 가설은 bullet point로 명확하게 작성할 것\n"
        "- 최종 개선 제안은 '현업 적용 아이디어'라는 제목의 테이블 형태로 출력할 것"
    )


# ── 자연어 → 필드 추출 ──
def extract_rcdo(description: str) -> dict:
    model = genai.GenerativeModel(
        model_name="gemini-3.1-flash-lite",
        system_instruction="""사용자가 설명한 데이터 분석 요구사항에서 아래 6가지 요소를 추출해주세요.
반드시 아래 형식 그대로만 출력하고, 다른 텍스트는 절대 포함하지 마세요.

ROLE: (분석 담당자의 역할 - 구체적으로)
CONTEXT: (분석의 목적, 배경, 기간)
DATA: (사용할 데이터 설명 - 파일 형태, 건수, 컬럼 등)
OUTPUT: (원하는 결과 내용 - 구체적인 항목 포함)
AUDIENCE: (결과를 볼 대상. 언급 없으면 "팀 내부 공유용")
PRIORITY: (분석의 핵심 초점. 언급 없으면 "종합적인 현황 파악")"""
    )
    response = model.generate_content(description)
    text = response.text.strip()

    result = {k: "" for k in ["ROLE", "CONTEXT", "DATA", "OUTPUT", "AUDIENCE", "PRIORITY"]}
    current_key = None
    for line in text.split("\n"):
        matched = False
        for key in result:
            if line.startswith(f"{key}:"):
                current_key = key
                result[key] = line[len(key) + 1:].strip()
                matched = True
                break
        if not matched and current_key and line.strip():
            result[current_key] += " " + line.strip()
    return result


# ── 프롬프트 생성 ──
OUTPUT_TYPE_OPTIONS = [
    "📊 표 (Table)", "📝 마크다운 헤더/섹션", "✍️ 서술형 (내러티브)",
    "🔧 JSON", "• 불릿 리스트", "📈 시각화 권장"
]

SYSTEM_INSTRUCTIONS = {
    "Claude": """당신은 Claude(Anthropic)에 최적화된 데이터 분석 프롬프트 전문가입니다.
입력된 모든 정보를 바탕으로 Claude가 최고의 분석 결과를 내도록 설계된 프롬프트를 작성하고,
왜 그렇게 작성했는지 간단히 설명해주세요.

Claude 최적화 프롬프트 작성 원칙:
1. XML 태그로 섹션 구분 — Claude는 XML 구조에 최적화되어 있음
2. <role>: "당신은 ~입니다" 형태로 역할 지정
3. <context>: 분석 목적·배경·기간 명확히 기술
4. <data>: 데이터 설명 포함. 실제 샘플 데이터가 있으면 그대로 포함. 파일 첨부 시 명시.
5. <audience>: 결과를 볼 대상과 그에 맞는 추상화 수준 안내
6. <priority>: 분석의 핵심 초점과 우선순위 명시
7. <task>: 출력 항목을 - 기호로 구체적으로 나열
8. <format>: 출력 형식 명확히 지정 (표, 마크다운, 서술형, JSON 등)

반드시 아래 형식 그대로만 출력하세요:

PROMPT:
(Claude 최적화 프롬프트. XML 태그 8개 모두 사용. 각 태그는 새 줄에 작성.)

EXPLANATION:
(이 프롬프트를 이렇게 구성한 이유를 2~3문장으로. 각 태그가 Claude에 왜 효과적인지 포함.)""",

    "Gemini": """당신은 Google Gemini에 최적화된 데이터 분석 프롬프트 전문가입니다.
입력된 모든 정보를 바탕으로 Gemini가 최고의 분석 결과를 내도록 설계된 프롬프트를 작성하고,
왜 그렇게 작성했는지 간단히 설명해주세요.

Gemini 최적화 프롬프트 작성 원칙:
1. # 헤더로 섹션 구분 — Gemini는 마크다운 헤더 구조에 최적화되어 있음
2. # 역할 정의: "너는 [역할]야." 형태로 자연스럽게 지정 (구어체 권장)
3. # 배경 및 목적: "우리 서비스는 ~" 형태로 비즈니스 맥락과 분석 목적 서술
4. # 데이터 구조 안내: 컬럼명, 타입, 설명을 - 기호 목록으로 명시. 샘플 데이터는 코드블록(```)으로 포함.
5. # 요청 사항 (분석 가이드): 분석 요청을 1. 2. 3. 번호 목록으로 구체적으로 나열
6. # 출력 형식: 섹션별로 원하는 형식을 bullet로 명시 (bullet point / 코드블록 / 표 등)

반드시 아래 형식 그대로만 출력하세요:

PROMPT:
(Gemini 최적화 프롬프트. # 헤더 구조 사용. 구어체 자연스러운 문장. 요청 사항은 번호 목록.)

EXPLANATION:
(이 프롬프트를 이렇게 구성한 이유를 2~3문장으로. 각 섹션이 Gemini에 왜 효과적인지 포함.)"""
}


def generate_prompt_with_explanation(target_ai: str, fields: dict) -> tuple[str, str]:
    model = genai.GenerativeModel(
        model_name="gemini-3.1-flash-lite",
        system_instruction=SYSTEM_INSTRUCTIONS[target_ai]
    )

    if target_ai == "Claude":
        data_paste = fields.get("data_paste", "").strip()
        if data_paste:
            data_section = (
                f"데이터 설명: {fields['data_desc']}\n"
                f"실제 데이터 샘플:\n{data_paste}"
            )
        else:
            data_section = (
                f"데이터 설명: {fields['data_desc']}\n"
                f"(파일 첨부 예정 — Claude 대화창에 파일 업로드 필요)"
            )
        format_str = ", ".join(fields.get("output_types", [])) or "자유 형식"
        user_input = f"""역할(Role): {fields['role']}
맥락(Context): {fields['context']}
{data_section}
분석 우선순위(Priority): {fields.get('priority') or '종합적인 현황 파악'}
대상 독자(Audience): {fields.get('audience') or '팀 내부 공유용'}
원하는 출력 내용(Output): {fields['output_format']}
출력 형식(Format): {format_str}"""

    else:  # Gemini
        user_input = f"""역할 정의: {fields['g_role']}
배경 및 목적: {fields['g_background']}
데이터 구조 안내:
{fields['g_data_schema']}
요청 사항:
{fields['g_requests']}
출력 형식:
{fields['g_output_format']}"""

    response = model.generate_content(user_input)
    text = response.text.strip()

    if "PROMPT:" in text and "EXPLANATION:" in text:
        parts = text.split("EXPLANATION:")
        prompt_part = parts[0].replace("PROMPT:", "").strip()
        explanation_part = parts[1].strip()
    else:
        prompt_part = text
        explanation_part = ""

    return prompt_part, explanation_part


# ===================== UI =====================

st.title("🔍 데이터 분석 프롬프트 생성기")
st.markdown("데이터 분석 상황을 입력하면 선택한 AI에 최적화된 프롬프트를 만들어드립니다.")

st.divider()

# ── 섹션 1: AI 선택 + 자연어 입력 ──
st.subheader("🗣️ 어떤 분석을 하고 싶으신가요?")

# AI 선택 라디오
target_ai = st.radio(
    "✨ 어떤 AI용 프롬프트를 만들까요?",
    options=["Claude", "Gemini"],
    index=0 if st.session_state.get("target_ai", "Claude") == "Claude" else 1,
    horizontal=True,
    help="Claude는 XML 태그 구조, Gemini는 마크다운 헤더(#) 구조로 최적화된 프롬프트를 생성합니다."
)
st.session_state["target_ai"] = target_ai

if target_ai == "Claude":
    st.caption("🟠 Claude 최적화 — XML 태그(`<role>`, `<context>` 등) 구조로 생성됩니다.")
else:
    st.caption("🔵 Gemini 최적화 — 마크다운 헤더(`# 역할 정의`, `# 요청 사항` 등) 구조로 생성됩니다.")

st.markdown("데이터와 원하는 분석을 자유롭게 입력하면 아래 항목을 자동으로 채워드립니다.")

st.text_area(
    label="자유 입력",
    key="natural_input",
    placeholder=(
        "예: 우리 쇼핑몰의 지난 3개월 구매 데이터가 있는데, "
        "어떤 고객이 재구매를 많이 하는지 알고 싶어요. "
        "연령대·카테고리별로 분석해서 마케팅팀 팀장에게 보고하려고 합니다."
    ),
    height=110,
    label_visibility="collapsed",
)

col_ex, col_auto = st.columns([1, 3])
with col_ex:
    on_click_fn = fill_example if target_ai == "Claude" else fill_example_gemini
    st.button("📋 예시 채우기", use_container_width=True, on_click=on_click_fn)
with col_auto:
    if st.button("⚡ 자동 채우기", use_container_width=True):
        if not st.session_state["natural_input"].strip():
            st.warning("분석 내용을 먼저 입력해주세요.")
        else:
            with st.spinner("항목을 분석하고 있습니다..."):
                try:
                    rcdo = extract_rcdo(st.session_state["natural_input"])
                    if target_ai == "Claude":
                        st.session_state["role"] = rcdo.get("ROLE", "")
                        st.session_state["context"] = rcdo.get("CONTEXT", "")
                        st.session_state["data_desc"] = rcdo.get("DATA", "")
                        st.session_state["output_format"] = rcdo.get("OUTPUT", "")
                        st.session_state["audience"] = rcdo.get("AUDIENCE", "")
                        st.session_state["priority"] = rcdo.get("PRIORITY", "")
                    else:
                        st.session_state["g_role"] = rcdo.get("ROLE", "")
                        bg = rcdo.get("CONTEXT", "")
                        if rcdo.get("PRIORITY"):
                            bg += f" 분석의 핵심 초점은 {rcdo['PRIORITY']}."
                        st.session_state["g_background"] = bg
                        st.session_state["g_data_schema"] = rcdo.get("DATA", "")
                        st.session_state["g_requests"] = rcdo.get("OUTPUT", "")
                    st.rerun()
                except Exception as e:
                    st.error(f"오류 발생: {str(e)}")

st.divider()

# ── 섹션 2: 상세 입력 ──
col_title, col_btn = st.columns([4, 1])
with col_title:
    st.subheader("📝 분석 정보 입력")
with col_btn:
    st.write("")
    st.button("🔄 초기화", use_container_width=True, on_click=clear_all)

st.markdown("자동으로 채워진 내용을 직접 수정할 수 있습니다.")

if target_ai == "Claude":
    # ① Role
    st.text_input(
        "① 역할 (Role)",
        key="role",
        placeholder="예: CS팀 주간 보고 담당자",
        help="분석을 수행하는 담당자의 역할"
    )
    # ② Context
    st.text_area(
        "② 맥락 (Context)",
        key="context",
        placeholder="예: 4월 상담 데이터를 분석해서 팀장 주간 보고용 요약을 만들어야 함",
        height=90,
        help="분석의 목적과 배경"
    )
    # ③ Data
    st.text_area(
        "③ 데이터 설명 (Data)",
        key="data_desc",
        placeholder="예: 4월 고객 상담 로그 551건 CSV — 컬럼: 날짜, 채널, 카테고리, 처리시간",
        height=90,
        help="파일명, 건수, 컬럼 구조 등 데이터의 특성을 설명"
    )
    with st.expander("📎 데이터 직접 붙여넣기  (선택 · 파일 첨부가 어려운 경우)"):
        st.caption(
            "Claude가 파일을 인식하지 못하거나 텍스트로 데이터를 전달할 때 사용하세요. "
            "CSV 헤더+샘플 행, JSON 일부, 또는 표 형태로 붙여넣으면 됩니다."
        )
        st.text_area(
            label="데이터 붙여넣기",
            key="data_paste",
            placeholder=(
                "customer_id,date,category,channel,duration\n"
                "1001,2024-04-01,반품,채팅,8분\n"
                "1002,2024-04-01,배송문의,전화,12분\n"
                "..."
            ),
            height=120,
            label_visibility="collapsed",
        )
    # ④ Output
    st.text_area(
        "④ 원하는 출력 내용 (Output)",
        key="output_format",
        placeholder="예: 채널별 상담 건수 집계 + 카테고리별 TOP3 이슈 + 이번 달 특이사항 2~3가지",
        height=90,
        help="결과에 반드시 포함되어야 할 항목들을 나열하세요."
    )
    # 보강 참조값 구분선
    st.markdown(
        "<div style='color:#c0c0c0; font-size:0.76em; text-align:center; padding:16px 0 4px;'>"
        "· · · &nbsp; 보강 참조값 &nbsp;(선택) &nbsp; · · ·</div>",
        unsafe_allow_html=True
    )
    # ⑤ Priority
    st.text_area(
        "⑤ 분석 우선순위 / 핵심 초점 (Priority)",
        key="priority",
        placeholder="예: 반복 민원 패턴 파악이 최우선, 그 다음 채널별 처리 시간 비교",
        height=75,
        help="분석에서 가장 중요하게 봐야 할 것. 비워두면 종합 현황 파악으로 설정됩니다."
    )
    # ⑥ Audience
    st.text_input(
        "⑥ 대상 독자 / 활용 목적 (Audience)",
        key="audience",
        placeholder="예: 팀장 보고용 · 비개발자 마케터 · 임원 요약본 · 외부 클라이언트",
        help="결과를 보는 사람에 따라 추상화 수준과 설명 깊이가 달라집니다."
    )
    # ⑦ Format
    st.multiselect(
        "⑦ 출력 형식 선택 (Format)",
        options=OUTPUT_TYPE_OPTIONS,
        key="output_types",
        help="원하는 출력 형식을 하나 이상 선택하세요. 선택하지 않으면 자유 형식으로 생성됩니다."
    )

else:  # Gemini 필드
    # ① 역할 정의
    st.text_input(
        "① 역할 정의",
        key="g_role",
        placeholder="예: 고객 서비스 데이터를 분석하는 5년 차 시니어 데이터 분석가",
        help="'너는 [역할]야.' 형태로 Gemini에게 전달됩니다."
    )
    # ② 배경 및 목적
    st.text_area(
        "② 배경 및 목적",
        key="g_background",
        placeholder=(
            "예: 우리 서비스는 최근 이메일 채널 재문의율이 높아지는 문제를 겪고 있어. "
            "이번 분석의 목적은 어떤 고객군에서 재문의가 집중되는지 파악하는 거야."
        ),
        height=110,
        help="비즈니스 상황 + 분석 목적을 구어체로 자연스럽게 서술하세요."
    )
    # ③ 데이터 구조 안내
    st.text_area(
        "③ 데이터 구조 안내",
        key="g_data_schema",
        placeholder=(
            "- customer_id: 고객 고유 ID (String)\n"
            "- channel: 상담 채널 (전화/채팅/이메일)\n"
            "- recontact_yn: 재문의 여부 (Y/N)\n"
            "- satisfaction: 만족도 점수 (1~5점)"
        ),
        height=130,
        help="컬럼명: 설명 (타입) 형태로 스키마를 입력하세요. 샘플 데이터가 있으면 아래에 추가하세요."
    )
    # ④ 요청 사항
    st.text_area(
        "④ 요청 사항 (분석 가이드)",
        key="g_requests",
        placeholder=(
            "1. 채널별 재문의율을 계산하고 가장 높은 채널과 낮은 채널을 비교해줘.\n"
            "2. 재문의 고객과 아닌 고객의 만족도 평균을 등급별로 분석해줘.\n"
            "3. 분석 결과를 바탕으로 현업 개선 아이디어 3가지를 제안해줘."
        ),
        height=130,
        help="원하는 분석을 번호 목록(1. 2. 3.)으로 구체적으로 입력하세요."
    )
    # ⑤ 출력 형식
    st.text_area(
        "⑤ 출력 형식",
        key="g_output_format",
        placeholder=(
            "- 채널별 비교는 표(테이블) 형태로 출력할 것\n"
            "- 핵심 가설은 bullet point로 명확하게 작성할 것\n"
            "- 최종 제안은 '현업 적용 아이디어' 테이블로 출력할 것"
        ),
        height=100,
        help="각 요청 결과물의 형식을 bullet로 지정하세요."
    )

st.divider()

# ── 프롬프트 생성 ──
if st.button("✨ 프롬프트 생성하기", type="primary", use_container_width=True):
    target_ai_val = st.session_state.get("target_ai", "Claude")

    if target_ai_val == "Claude":
        fields = {
            "role":         st.session_state.get("role", ""),
            "context":      st.session_state.get("context", ""),
            "data_desc":    st.session_state.get("data_desc", ""),
            "data_paste":   st.session_state.get("data_paste", ""),
            "priority":     st.session_state.get("priority", ""),
            "audience":     st.session_state.get("audience", ""),
            "output_format": st.session_state.get("output_format", ""),
            "output_types": st.session_state.get("output_types", []),
        }
        required = {
            "① 역할": fields["role"],
            "② 맥락": fields["context"],
            "③ 데이터 설명": fields["data_desc"],
            "④ 출력 내용": fields["output_format"],
        }
    else:
        fields = {
            "g_role":          st.session_state.get("g_role", ""),
            "g_background":    st.session_state.get("g_background", ""),
            "g_data_schema":   st.session_state.get("g_data_schema", ""),
            "g_requests":      st.session_state.get("g_requests", ""),
            "g_output_format": st.session_state.get("g_output_format", ""),
        }
        required = {
            "① 역할 정의": fields["g_role"],
            "② 배경 및 목적": fields["g_background"],
            "③ 데이터 구조": fields["g_data_schema"],
            "④ 요청 사항": fields["g_requests"],
        }

    missing = [k for k, v in required.items() if not v.strip()]
    if missing:
        st.warning(f"필수 항목을 입력해주세요: {', '.join(missing)}")
    else:
        with st.spinner("프롬프트를 생성하고 있습니다..."):
            try:
                prompt, explanation = generate_prompt_with_explanation(target_ai_val, fields)

                ai_label = target_ai_val
                st.subheader(f"✅ 생성된 분석 프롬프트 ({ai_label} 최적화)")
                st.info(f"아래 프롬프트를 복사한 후 {ai_label}에 붙여넣고, 데이터 파일을 첨부하세요.")
                st.code(prompt, language=None)

                if explanation:
                    st.subheader("💬 이렇게 구성한 이유")
                    st.markdown(explanation)

                with st.expander("📌 입력 정보 요약"):
                    if target_ai_val == "Claude":
                        rcdo_rows = [
                            ("R", "Role (역할)", fields["role"]),
                            ("C", "Context (맥락)", fields["context"]),
                            ("D", "Data (데이터)", fields["data_desc"] + (" · 샘플 데이터 포함" if fields["data_paste"].strip() else "")),
                            ("O", "Output (출력 내용)", fields["output_format"]),
                        ]
                        extra_rows = [
                            ("P", "Priority (우선순위)", fields["priority"] or "종합적인 현황 파악"),
                            ("A", "Audience (대상 독자)", fields["audience"] or "팀 내부 공유용"),
                            ("F", "Format (출력 형식)", ", ".join(fields["output_types"]) if fields["output_types"] else "자유 형식"),
                        ]
                        rcdo_table = "**RCDO 기본 구조**\n\n| 요소 | 항목 | 입력 내용 |\n|:---:|------|--------|\n"
                        for r in rcdo_rows:
                            rcdo_table += f"| **{r[0]}** | **{r[1]}** | {r[2]} |\n"
                        extra_table = "\n**보강 참조값**\n\n| 요소 | 항목 | 입력 내용 |\n|:---:|------|--------|\n"
                        for r in extra_rows:
                            extra_table += f"| {r[0]} | {r[1]} | {r[2]} |\n"
                        st.markdown(rcdo_table + extra_table)
                    else:
                        gemini_rows = [
                            ("①", "역할 정의", fields["g_role"]),
                            ("②", "배경 및 목적", fields["g_background"]),
                            ("③", "데이터 구조 안내", fields["g_data_schema"].replace("\n", " / ")),
                            ("④", "요청 사항", fields["g_requests"].replace("\n", " / ")),
                            ("⑤", "출력 형식", fields["g_output_format"].replace("\n", " / ")),
                        ]
                        table = "**Gemini 프롬프트 구조**\n\n| # | 섹션 | 입력 내용 |\n|:---:|------|--------|\n"
                        for r in gemini_rows:
                            table += f"| **{r[0]}** | **{r[1]}** | {r[2]} |\n"
                        st.markdown(table)

            except Exception as e:
                st.error(f"생성 중 오류가 발생했습니다: {str(e)}")

st.divider()
st.markdown("""
<style>
.api-footer { display: flex; align-items: center; gap: 6px; font-size: 0.82em; color: #888; }
.api-tooltip { position: relative; display: inline-block; cursor: help; }
.api-tooltip .tooltiptext {
  visibility: hidden; opacity: 0;
  width: 300px;
  background-color: #2c2c2c; color: #f0f0f0;
  text-align: left; border-radius: 8px; padding: 10px 14px;
  position: absolute; z-index: 9999;
  bottom: 140%; left: 50%; transform: translateX(-50%);
  font-size: 13px; line-height: 1.8;
  transition: opacity 0.2s ease;
  pointer-events: none;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}
.api-tooltip:hover .tooltiptext { visibility: visible; opacity: 1; }
.q-mark {
  display: inline-flex; align-items: center; justify-content: center;
  width: 16px; height: 16px; border-radius: 50%;
  background-color: #aaa; color: white;
  font-size: 11px; font-weight: bold; line-height: 1;
  cursor: help;
}
</style>
<div class="api-footer">
  💡 Powered by Google Gemini &nbsp;·&nbsp; AI LLM 데이터 분석 과정
  <span class="api-tooltip">
    <span class="q-mark">?</span>
    <span class="tooltiptext">
      <b>Gemini 무료 티어 제한</b><br>
      • 분당 요청 수 (RPM)&nbsp;: 10 RPM<br>
      • 분당 토큰 수 (TPM)&nbsp;: 250,000 TPM<br>
      • 일일 요청 수 (RPD)&nbsp;: 250 RPD<br>
      &nbsp;&nbsp;<span style="font-size:12px;color:#bbb;">(태평양 표준시 기준 자정 리셋)</span>
    </span>
  </span>
</div>
""", unsafe_allow_html=True)
