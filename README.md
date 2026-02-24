# Missouri IFP Guided Interview (Gradio)

This repository contains a standalone Gradio web app that guides users through a Missouri In Forma Pauperis (IFP) interview and generates a filled PDF.

## Include the template PDF in the repo

1. Place your source court form PDF in the repository root.
2. Name it exactly:

   `Missouri - InFormaPauperis.pdf`

   (or update `TEMPLATE_PDF_PATH` in `app.py` to match your chosen path).
3. Commit that PDF so it is available to Hugging Face Spaces at runtime.

## Hugging Face Spaces configuration

1. Create a new **Space** and select **Gradio** as the SDK.
2. Push these files to the Space repo:
   - `app.py`
   - `requirements.txt`
   - `Missouri - InFormaPauperis.pdf`
3. In the Space settings, add a Secret:
   - **Name:** `OPENAI_API_KEY`
   - **Value:** your OpenAI API key
4. Restart the Space after adding/updating secrets.

## Local run (optional)

```bash
pip install -r requirements.txt
python app.py
```

Then open: `http://localhost:7860`
