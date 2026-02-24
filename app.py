import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List

import gradio as gr
from openai import OpenAI
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
# Keep the template PDF in the repository root (same folder as this app.py),
# or change this path to wherever you store the source form.
TEMPLATE_PDF_PATH = "Missouri - InFormaPauperis.pdf"

# Coordinates for each field on each PDF page.
# IMPORTANT: You must fine-tune these x/y values so they match your exact PDF.
# reportlab uses points with origin at the bottom-left corner.
# Format: key -> (page_index, x, y)
PDF_FIELD_POSITIONS = {
    "full_name": (0, 120, 700),
    "address": (0, 120, 680),
    "city_state_zip": (0, 120, 660),
    "phone": (0, 120, 640),
    "email": (0, 360, 640),
    "case_type": (0, 120, 615),
    "employment_status": (0, 120, 590),
    "monthly_income": (0, 120, 570),
    "cash_on_hand": (0, 120, 550),
    "bank_balance": (0, 120, 530),
    "monthly_expenses": (0, 120, 510),
    "dependents": (0, 120, 490),
    "government_assistance": (0, 120, 470),
    "debts": (0, 120, 450),
    "hardship_explanation": (0, 120, 420),
    "date_signed": (0, 120, 160),
    "signature_name": (0, 360, 160),
}


@dataclass
class Question:
    key: str
    label: str
    qtype: str  # text, number, radio, multiline, date
    choices: List[str] | None = None
    placeholder: str = ""


QUESTIONS: List[Question] = [
    Question("full_name", "Your full legal name", "text", placeholder="Jane Doe"),
    Question("address", "Street address", "text", placeholder="123 Main St"),
    Question("city_state_zip", "City, State, ZIP", "text", placeholder="Springfield, MO 65807"),
    Question("phone", "Phone number", "text", placeholder="(555) 555-5555"),
    Question("email", "Email (optional)", "text", placeholder="name@example.com"),
    Question(
        "case_type",
        "Type of case",
        "radio",
        choices=[
            "Dissolution of Marriage (Divorce)",
            "Legal Separation",
            "Modification/Post-Decree",
            "Other Family Law",
        ],
    ),
    Question(
        "employment_status",
        "Employment status",
        "radio",
        choices=["Employed", "Unemployed", "Self-employed", "Disabled", "Retired"],
    ),
    Question("monthly_income", "Total monthly income (USD)", "number", placeholder="0"),
    Question("cash_on_hand", "Cash on hand (USD)", "number", placeholder="0"),
    Question("bank_balance", "Total bank account balances (USD)", "number", placeholder="0"),
    Question("monthly_expenses", "Average monthly expenses (USD)", "number", placeholder="0"),
    Question("dependents", "Number of dependents you support", "number", placeholder="0"),
    Question(
        "government_assistance",
        "Do you receive public benefits? If yes, list programs.",
        "multiline",
        placeholder="Example: SNAP, Medicaid, TANF",
    ),
    Question("debts", "Briefly list significant debts", "multiline", placeholder="Credit cards, medical bills, etc."),
    Question(
        "hardship_explanation",
        "Explain why you cannot afford filing fees",
        "multiline",
        placeholder="Briefly describe your financial hardship.",
    ),
    Question("date_signed", "Date (MM/DD/YYYY)", "text", placeholder="MM/DD/YYYY"),
    Question("signature_name", "Type your name as signature", "text", placeholder="Jane Doe"),
]


def default_state() -> Dict[str, Any]:
    return {
        "step": 0,
        "answers": {q.key: "" for q in QUESTIONS},
    }


def current_question(step: int) -> Question:
    step = max(0, min(step, len(QUESTIONS) - 1))
    return QUESTIONS[step]


def normalize_value(value: Any, qtype: str) -> str:
    if value is None:
        return ""
    if qtype == "number":
        # Preserve integers cleanly while supporting decimal entries.
        try:
            n = float(value)
            return str(int(n)) if n.is_integer() else f"{n:.2f}"
        except Exception:
            return str(value)
    return str(value)


def ui_for_question(q: Question, value: str):
    """Create component update payloads so one input widget is shown at a time."""
    hidden = gr.update(visible=False)

    text_update = hidden
    number_update = hidden
    radio_update = hidden
    multiline_update = hidden

    if q.qtype == "text":
        text_update = gr.update(visible=True, label=q.label, value=value, placeholder=q.placeholder)
    elif q.qtype == "number":
        num_value = None
        if value != "":
            try:
                num_value = float(value)
            except Exception:
                num_value = None
        number_update = gr.update(visible=True, label=q.label, value=num_value, placeholder=q.placeholder)
    elif q.qtype == "radio":
        radio_update = gr.update(visible=True, label=q.label, choices=q.choices or [], value=value or None)
    elif q.qtype == "multiline":
        multiline_update = gr.update(visible=True, label=q.label, value=value, placeholder=q.placeholder)

    progress = f"Question {QUESTIONS.index(q) + 1} of {len(QUESTIONS)}"
    return text_update, number_update, radio_update, multiline_update, progress


def save_answer_and_move(state: Dict[str, Any], text_val, number_val, radio_val, multiline_val, delta: int):
    step = state["step"]
    q = current_question(step)

    raw_val = ""
    if q.qtype == "text":
        raw_val = text_val
    elif q.qtype == "number":
        raw_val = number_val
    elif q.qtype == "radio":
        raw_val = radio_val
    elif q.qtype == "multiline":
        raw_val = multiline_val

    state["answers"][q.key] = normalize_value(raw_val, q.qtype)

    new_step = max(0, min(step + delta, len(QUESTIONS) - 1))
    state["step"] = new_step
    q2 = current_question(new_step)
    existing = state["answers"].get(q2.key, "")

    text_u, num_u, radio_u, multi_u, prog = ui_for_question(q2, existing)

    can_go_back = new_step > 0
    is_last = new_step == len(QUESTIONS) - 1

    return (
        state,
        text_u,
        num_u,
        radio_u,
        multi_u,
        prog,
        gr.update(interactive=can_go_back),
        gr.update(value="Finish & Generate PDF" if is_last else "Next"),
    )


def start_interview(state: Dict[str, Any]):
    state = default_state()
    q = current_question(0)
    text_u, num_u, radio_u, multi_u, prog = ui_for_question(q, "")
    return (
        state,
        text_u,
        num_u,
        radio_u,
        multi_u,
        prog,
        gr.update(interactive=False),
        gr.update(value="Next"),
        "",
    )


def explain_question(state: Dict[str, Any]) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Explanation unavailable: OPENAI_API_KEY is not configured."

    q = current_question(state["step"])
    prompt = (
        "You are a legal information assistant for Missouri family law users. "
        "Explain the following intake question in plain language (2-4 sentences). "
        "Do NOT give legal advice. Keep it practical and neutral.\n\n"
        f"Question: {q.label}"
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": "You provide plain-language legal form guidance."},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Could not generate explanation right now: {e}"


def create_overlay_pdf(answers: Dict[str, str], num_pages: int) -> str:
    """Generate an overlay PDF where answers are written at mapped coordinates."""
    tmp_overlay = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    overlay_path = tmp_overlay.name
    tmp_overlay.close()

    c = canvas.Canvas(overlay_path, pagesize=letter)

    for page_index in range(num_pages):
        for key, (p_idx, x, y) in PDF_FIELD_POSITIONS.items():
            if p_idx != page_index:
                continue
            value = answers.get(key, "")
            if value:
                c.setFont("Helvetica", 10)
                c.drawString(x, y, value)
        c.showPage()

    c.save()
    return overlay_path


def fill_pdf(answers: Dict[str, str]) -> str:
    if not os.path.exists(TEMPLATE_PDF_PATH):
        raise FileNotFoundError(
            f"Template PDF not found at '{TEMPLATE_PDF_PATH}'. "
            "Place the IFP form in the repository and update TEMPLATE_PDF_PATH if needed."
        )

    template_reader = PdfReader(TEMPLATE_PDF_PATH)
    num_pages = len(template_reader.pages)

    overlay_path = create_overlay_pdf(answers, num_pages)
    overlay_reader = PdfReader(overlay_path)

    writer = PdfWriter()
    for i in range(num_pages):
        base_page = template_reader.pages[i]
        if i < len(overlay_reader.pages):
            base_page.merge_page(overlay_reader.pages[i])
        writer.add_page(base_page)

    output_file = tempfile.NamedTemporaryFile(delete=False, suffix="_ifp_completed.pdf")
    output_path = output_file.name
    output_file.close()

    with open(output_path, "wb") as f:
        writer.write(f)

    return output_path


def on_next_or_finish(state: Dict[str, Any], text_val, number_val, radio_val, multiline_val):
    at_last = state["step"] == len(QUESTIONS) - 1
    (
        state,
        text_u,
        num_u,
        radio_u,
        multi_u,
        prog,
        back_u,
        next_u,
    ) = save_answer_and_move(state, text_val, number_val, radio_val, multiline_val, delta=(0 if at_last else 1))

    download_update = gr.update(value=None, visible=False)
    status = ""

    if at_last:
        try:
            output_path = fill_pdf(state["answers"])
            download_update = gr.update(value=output_path, visible=True)
            status = "PDF generated successfully. Review and sign where required before filing."
        except Exception as e:
            status = f"Could not generate PDF: {e}"

    return state, text_u, num_u, radio_u, multi_u, prog, back_u, next_u, download_update, status


def on_back(state: Dict[str, Any], text_val, number_val, radio_val, multiline_val):
    return save_answer_and_move(state, text_val, number_val, radio_val, multiline_val, delta=-1)


with gr.Blocks(title="Missouri IFP Guided Interview") as demo:
    gr.Markdown(
        """
# Missouri In Forma Pauperis (IFP) Guided Interview
This tool helps you draft a completed IFP fee waiver form for divorce-related cases in Missouri.
It is for **information and form preparation**, not legal advice.
"""
    )

    state = gr.State(default_state())

    progress = gr.Markdown("Question 1 of 17")

    text_input = gr.Textbox(visible=False)
    number_input = gr.Number(visible=False)
    radio_input = gr.Radio(visible=False)
    multiline_input = gr.Textbox(lines=5, visible=False)

    with gr.Row():
        back_btn = gr.Button("Back", interactive=False)
        next_btn = gr.Button("Next")
        explain_btn = gr.Button("Explain this question")

    explanation_box = gr.Markdown("")

    status_box = gr.Markdown("")
    download_file = gr.File(label="Download completed IFP PDF", visible=False)

    gr.Markdown(
        """
### Notes
- You should verify all entries for accuracy.
- This app places text based on coordinate mappings. You may need to tune `PDF_FIELD_POSITIONS` for your exact PDF.
- Some courts may require original signatures or additional local forms.
"""
    )

    demo.load(
        start_interview,
        inputs=[state],
        outputs=[
            state,
            text_input,
            number_input,
            radio_input,
            multiline_input,
            progress,
            back_btn,
            next_btn,
            explanation_box,
        ],
    )

    next_btn.click(
        on_next_or_finish,
        inputs=[state, text_input, number_input, radio_input, multiline_input],
        outputs=[
            state,
            text_input,
            number_input,
            radio_input,
            multiline_input,
            progress,
            back_btn,
            next_btn,
            download_file,
            status_box,
        ],
    )

    back_btn.click(
        on_back,
        inputs=[state, text_input, number_input, radio_input, multiline_input],
        outputs=[
            state,
            text_input,
            number_input,
            radio_input,
            multiline_input,
            progress,
            back_btn,
            next_btn,
        ],
    )

    explain_btn.click(
        explain_question,
        inputs=[state],
        outputs=[explanation_box],
    )


if __name__ == "__main__":
    # For Hugging Face Spaces, default launch behavior works.
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
