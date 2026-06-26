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
    "role": "",
    "context": "",
    "data_desc": "",
    "data_paste": "",
    "priority": "",
    "audience": "",
    "output_format": "",
    "output_types": [],
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


# ── 자연어 → RCDO + 확장 요소 추출 ──
def extract_rcdo(description: str) -> dict:
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
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


# ── Claude 최적화 프롬프트 생성 ──
OUTPUT_TYPE_OPTIONS = [
    "📊 표 (Table)", "📝 마크다운 헤더/섹션", "✍️ 서술형 (내러티브)",
    "🔧 JSON", "• 불릿 리스트", "📈 시각화 권장"
]


def generate_prompt_with_explanation(
    role, context, data_desc, data_paste,
    priority, audience, output_content, output_types
) -> tuple[str, str]:
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction="""당신은 Claude(Anthropic)에 최적화된 데이터 분석 프롬프트 전문가입니다.
입력된 모든 정보를 바탕으로 Claude가 최고의 분석 결과를 내도록 설계된 프롬프트를 작성하고,
왜 그렇게 작성했는지 간단히 설명해주세요.

Claude 최적화 프롬프트 작성 원칙:
1. XML 태그로 섹션 구분 — Claude는 XML 구조에 최적화되어 있음
2. <role>: "당신은 ~입니다" 형태로 역할 지정
3. <context>: 분석 목적·배경·기간 명확히 기술
4. <data>: 데이터 설명 포함. 실제 샘플 데이터가 있으면 그대로 포함. 파일 첨부 시 명시.
   데이터가 없거나 파일 첨부 불가 시, 사용자가 핵심 수치나 구조를 직접 입력하도록 안내.
5. <audience>: 결과를 볼 대상과 그에 맞는 추상화 수준 안내
6. <priority>: 분석의 핵심 초점과 우선순위 명시
7. <task>: 출력 항목을 - 기호로 구체적으로 나열
8. <format>: 출력 형식 명확히 지정 (표, 마크다운, 서술형, JSON 등)

반드시 아래 형식 그대로만 출력하세요:

PROMPT:
(Claude 최적화 프롬프트. XML 태그 8개 모두 사용. 각 태그는 새 줄에 작성.)

EXPLANATION:
(이 프롬프트를 이렇게 구성한 이유를 2~3문장으로. 각 태그가 Claude에 왜 효과적인지 포함.)"""
    )

    # <data> 섹션 구성
    if data_paste.strip():
        data_section = (
            f"데이터 설명: {data_desc}\n"
            f"실제 데이터 샘플 (사용자 직접 입력):\n{data_paste.strip()}"
        )
    else:
        data_section = (
            f"데이터 설명: {data_desc}\n"
            f"(파일 첨부 예정 — Claude 대화창에 파일 업로드 필요)"
        )

    format_str = ", ".join(output_types) if output_types else "자유 형식"

    user_input = f"""역할(Role): {role}
맥락(Context): {context}
{data_section}
분석 우선순위(Priority): {priority or "종합적인 현황 파악"}
대상 독자(Audience): {audience or "팀 내부 공유용"}
원하는 출력 내용(Output): {output_content}
출력 형식(Format): {format_str}"""

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
st.markdown("데이터 분석 상황을 입력하면 **Claude에 최적화된** 프롬프트를 만들어드립니다.")

st.divider()

# ── 섹션 1: 자연어 입력 ──
st.subheader("🗣️ 어떤 분석을 하고 싶으신가요?")
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
    st.button("📋 예시 채우기", use_container_width=True, on_click=fill_example)
with col_auto:
    if st.button("⚡ 자동 채우기", use_container_width=True):
        if not st.session_state["natural_input"].strip():
            st.warning("분석 내용을 먼저 입력해주세요.")
        else:
            with st.spinner("항목을 분석하고 있습니다..."):
                try:
                    rcdo = extract_rcdo(st.session_state["natural_input"])
                    st.session_state["role"] = rcdo.get("ROLE", "")
                    st.session_state["context"] = rcdo.get("CONTEXT", "")
                    st.session_state["data_desc"] = rcdo.get("DATA", "")
                    st.session_state["output_format"] = rcdo.get("OUTPUT", "")
                    st.session_state["audience"] = rcdo.get("AUDIENCE", "")
                    st.session_state["priority"] = rcdo.get("PRIORITY", "")
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

# ① Role  — RCDO 기본
st.text_input(
    "① 역할 (Role)",
    key="role",
    placeholder="예: CS팀 주간 보고 담당자",
    help="분석을 수행하는 담당자의 역할"
)

# ② Context  — RCDO 기본
st.text_area(
    "② 맥락 (Context)",
    key="context",
    placeholder="예: 4월 상담 데이터를 분석해서 팀장 주간 보고용 요약을 만들어야 함",
    height=90,
    help="분석의 목적과 배경"
)

# ③ Data  — RCDO 기본
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

# ④ Output  — RCDO 기본
st.text_area(
    "④ 원하는 출력 내용 (Output)",
    key="output_format",
    placeholder="예: 채널별 상담 건수 집계 + 카테고리별 TOP3 이슈 + 이번 달 특이사항 2~3가지",
    height=90,
    help="결과에 반드시 포함되어야 할 항목들을 나열하세요."
)

# ── 보강 참조값 구분선 ──
st.markdown(
    "<div style='color:#c0c0c0; font-size:0.76em; text-align:center; padding:16px 0 4px;'>"
    "· · · &nbsp; 보강 참조값 &nbsp;(선택) &nbsp; · · ·</div>",
    unsafe_allow_html=True
)

# ⑤ Priority  — 선택
st.text_area(
    "⑤ 분석 우선순위 / 핵심 초점 (Priority)",
    key="priority",
    placeholder="예: 반복 민원 패턴 파악이 최우선, 그 다음 채널별 처리 시간 비교",
    height=75,
    help="분석에서 가장 중요하게 봐야 할 것. 비워두면 종합 현황 파악으로 설정됩니다."
)

# ⑥ Audience  — 선택
st.text_input(
    "⑥ 대상 독자 / 활용 목적 (Audience)",
    key="audience",
    placeholder="예: 팀장 보고용 · 비개발자 마케터 · 임원 요약본 · 외부 클라이언트",
    help="결과를 보는 사람에 따라 추상화 수준과 설명 깊이가 달라집니다. 비워두면 팀 내부 공유용으로 설정됩니다."
)

# ⑦ Format  — 선택
st.multiselect(
    "⑦ 출력 형식 선택 (Format)",
    options=OUTPUT_TYPE_OPTIONS,
    key="output_types",
    help="원하는 출력 형식을 하나 이상 선택하세요. 선택하지 않으면 자유 형식으로 생성됩니다."
)

st.divider()

# ── 프롬프트 생성 ──
if st.button("✨ 프롬프트 생성하기", type="primary", use_container_width=True):
    role_val        = st.session_state.get("role", "")
    context_val     = st.session_state.get("context", "")
    data_val        = st.session_state.get("data_desc", "")
    data_paste_val  = st.session_state.get("data_paste", "")
    priority_val    = st.session_state.get("priority", "")
    audience_val    = st.session_state.get("audience", "")
    output_val      = st.session_state.get("output_format", "")
    output_types_val = st.session_state.get("output_types", [])

    required = {"① 역할": role_val, "② 맥락": context_val, "③ 데이터 설명": data_val, "④ 출력 내용": output_val}
    missing = [k for k, v in required.items() if not v.strip()]
    if missing:
        st.warning(f"필수 항목을 입력해주세요: {', '.join(missing)}")
    else:
        with st.spinner("프롬프트를 생성하고 있습니다..."):
            try:
                prompt, explanation = generate_prompt_with_explanation(
                    role_val, context_val, data_val, data_paste_val,
                    priority_val, audience_val, output_val, output_types_val
                )

                st.subheader("✅ 생성된 분석 프롬프트")
                st.info("아래 프롬프트를 복사한 후 Claude에 붙여넣고, 데이터 파일을 첨부하세요.")
                st.code(prompt, language=None)

                if explanation:
                    st.subheader("💬 이렇게 구성한 이유")
                    st.markdown(explanation)

                with st.expander("📌 입력 정보 요약"):
                    rcdo_rows = [
                        ("R", "Role (역할)", role_val),
                        ("C", "Context (맥락)", context_val),
                        ("D", "Data (데이터)", data_val + (" · 샘플 데이터 포함" if data_paste_val.strip() else "")),
                        ("O", "Output (출력 내용)", output_val),
                    ]
                    extra_rows = [
                        ("P", "Priority (우선순위)", priority_val or "종합적인 현황 파악"),
                        ("A", "Audience (대상 독자)", audience_val or "팀 내부 공유용"),
                        ("F", "Format (출력 형식)", ", ".join(output_types_val) if output_types_val else "자유 형식"),
                    ]

                    rcdo_table = "**RCDO 기본 구조**\n\n| 요소 | 항목 | 입력 내용 |\n|:---:|------|--------|\n"
                    for r in rcdo_rows:
                        rcdo_table += f"| **{r[0]}** | **{r[1]}** | {r[2]} |\n"

                    extra_table = "\n**보강 참조값**\n\n| 요소 | 항목 | 입력 내용 |\n|:---:|------|--------|\n"
                    for r in extra_rows:
                        extra_table += f"| {r[0]} | {r[1]} | {r[2]} |\n"

                    st.markdown(rcdo_table + extra_table)

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
      <b>Gemini 2.5 Flash 무료 티어 제한</b><br>
      • 분당 요청 수 (RPM)&nbsp;: 10 RPM<br>
      • 분당 토큰 수 (TPM)&nbsp;: 250,000 TPM<br>
      • 일일 요청 수 (RPD)&nbsp;: 250 RPD<br>
      &nbsp;&nbsp;<span style="font-size:12px;color:#bbb;">(태평양 표준시 기준 자정 리셋)</span>
    </span>
  </span>
</div>
""", unsafe_allow_html=True)
