from flask import Flask, request, send_file, after_this_request, jsonify, render_template
from flask_cors import CORS
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
import tempfile, os, zipfile
from werkzeug.utils import secure_filename
import pikepdf
from pdf2docx import Converter
from PIL import Image
import logging
import traceback
from pdf2image import convert_from_path  # new: convert PDF pages to images
from io import BytesIO

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# configure logger early so exceptions are visible in container logs
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# show full trace in HTTP response when SHOW_STACK=1 (set this only for debugging)
# DEBUG MODE: default to showing stack so we can get the real traceback while debugging.
# Change back to "0" before production.
SHOW_STACK = os.environ.get("SHOW_STACK", "1") == "1"

@app.route('/')
def home():
    # test.html lives at project root; send it directly to avoid Jinja TemplateNotFound
    return send_file(os.path.join(app.root_path, "test.html"))

# quick health endpoint to verify container is up without touching conversion code
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

# global error handler to capture unexpected exceptions and log stacktrace
@app.errorhandler(Exception)
def handle_exception(e):
    # Log full traceback to container logs for debugging
    tb = traceback.format_exc()
    # include some request context to make logs actionable
    try:
        ctx_info = {
            "path": request.path,
            "method": request.method,
            "args": dict(request.args),
            "form_keys": list(request.form.keys()),
            "files": list(request.files.keys())
        }
    except Exception:
        ctx_info = {"path": "unknown"}
    app.logger.error("Unhandled exception on request %s: %s\nContext: %s\n%s", request.path if hasattr(request, "path") else "?", str(e), ctx_info, tb)

    # Return minimal info to client unless SHOW_STACK enabled
    if SHOW_STACK:
        return jsonify({"error": "Internal Server Error", "details": tb}), 500
    return jsonify({"error": "Internal Server Error"}), 500

# ... your other routes (split PDF, pdf-to-word, etc.)

# ---------------- HELPER ----------------
def safe_send_file(path, download_name):
    """Send file and delete after sending."""
    @after_this_request
    def cleanup(response):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        return response
    return send_file(path, as_attachment=True, download_name=download_name)

# small helper: zip list of file paths and return zip path
def _zip_files(file_paths, zip_name="output.zip"):
    zip_path = os.path.join(tempfile.gettempdir(), zip_name)
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for p in file_paths:
            zf.write(p, os.path.basename(p))
    return zip_path

# ---------------- MERGE PDFs ----------------
@app.route("/merge", methods=["POST"])
def merge_pdfs():
    if "files" not in request.files:
        return jsonify({"error": "No files uploaded"}), 400

    files = request.files.getlist("files")
    if len(files) < 2:
        return jsonify({"error": "Select at least two files"}), 400

    merger = PdfMerger()
    for file in files:
        merger.append(file)

    temp_merged_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    merger.write(temp_merged_pdf.name)
    merger.close()

    return safe_send_file(temp_merged_pdf.name, "merged.pdf")


# ---------------- SPLIT PDF ----------------
@app.route("/split", methods=["POST"])
def split_pdf():
    if "file" not in request.files or "start" not in request.form or "end" not in request.form:
        return jsonify({"error": "Provide file and start/end pages"}), 400

    file = request.files["file"]
    start = int(request.form["start"])
    end = int(request.form["end"])

    reader = PdfReader(file)
    writer = PdfWriter()
    for i in range(start - 1, end):
        writer.add_page(reader.pages[i])

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    with open(temp.name, "wb") as f:
        writer.write(f)

    return safe_send_file(temp.name, "split.pdf")

# ---------------- PDF → WORD ----------------
@app.route("/pdf-to-word", methods=["POST"])
def pdf_to_word():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    input_path = os.path.join(tempfile.gettempdir(), secure_filename(file.filename))
    file.save(input_path)
    output_path = input_path.replace(".pdf", ".docx")

    cv = Converter(input_path)
    cv.convert(output_path, start=0, end=None)
    cv.close()

    return safe_send_file(output_path, "converted.docx")

# ---------------- WORD → PDF ----------------
@app.route("/word-to-pdf", methods=["POST"])
def word_to_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    input_path = os.path.join(tempfile.gettempdir(), secure_filename(file.filename))
    file.save(input_path)

    output_dir = tempfile.gettempdir()
    base = os.path.splitext(secure_filename(file.filename))[0]
    output_path = os.path.join(output_dir, base + ".pdf")

    # Use LibreOffice headless conversion (soffice) which works on Linux containers
    cmd = f'soffice --headless --convert-to pdf --outdir "{output_dir}" "{input_path}"'
    os.system(cmd)

    if not os.path.exists(output_path):
        return jsonify({"error": "Conversion failed"}), 500

    return safe_send_file(output_path, "converted.pdf")

# ---------------- IMAGES → PDF ----------------
@app.route("/images-to-pdf", methods=["POST"])
def images_to_pdf():
    if "files" not in request.files:
        return jsonify({"error": "No images uploaded"}), 400

    files = request.files.getlist("files")
    images = [Image.open(f).convert("RGB") for f in files]

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    images[0].save(temp.name, save_all=True, append_images=images[1:])

    return safe_send_file(temp.name, "images_to_pdf.pdf")

# ---------------- ADD PASSWORD ----------------
@app.route("/add-password", methods=["POST"])
def add_password():
    if "file" not in request.files or "password" not in request.form:
        return jsonify({"error": "Provide file and password"}), 400

    file = request.files["file"]
    password = request.form["password"]

    reader = PdfReader(file)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(password)

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    with open(temp.name, "wb") as f:
        writer.write(f)

    return safe_send_file(temp.name, "protected.pdf")

# ---------------- UNLOCK PDF ----------------
@app.route("/unlock", methods=["POST"])
def unlock_pdf():
    if "file" not in request.files or "password" not in request.form:
        return jsonify({"error": "File and password required"}), 400

    uploaded = request.files["file"]
    password = request.form["password"]

    fd, input_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    uploaded.save(input_path)

    output_path = os.path.join(tempfile.gettempdir(), f"unlocked_{secure_filename(uploaded.filename)}")

    try:
        pdf = pikepdf.open(input_path, password=password)
        pdf.save(output_path)
        pdf.close()
        return safe_send_file(output_path, f"unlocked_{uploaded.filename}")
    except pikepdf._qpdf.PasswordError:
        return jsonify({"error": "Incorrect password"}), 401
    except Exception:
        try:
            reader = PdfReader(input_path)
            if reader.is_encrypted:
                reader.decrypt(password)
            writer = PdfWriter()
            for p in reader.pages:
                writer.add_page(p)
            with open(output_path, "wb") as f_out:
                writer.write(f_out)
            return safe_send_file(output_path, f"unlocked_{uploaded.filename}")
        except Exception as e2:
            return jsonify({"error": "Failed to unlock PDF", "details": str(e2)}), 500
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)

# ---------------- PPT → PDF ----------------
@app.route("/ppt-to-pdf", methods=["POST"])
def ppt_to_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    input_path = os.path.join(tempfile.gettempdir(), secure_filename(file.filename))
    file.save(input_path)
    output_dir = tempfile.gettempdir()
    output_path = os.path.join(output_dir, file.filename.replace(".pptx", ".pdf"))

    cmd = f'soffice --headless --convert-to pdf --outdir "{output_dir}" "{input_path}"'
    os.system(cmd)

    if not os.path.exists(output_path):
        return jsonify({"error": "Conversion failed"}), 500

    return safe_send_file(output_path, "converted.pdf")

# ---------------- IMAGE RESIZER + COMPRESSOR (MULTIPLE FILES) ----------------
@app.route("/resize-compress-image", methods=["POST"])
def resize_compress_image():
    if "files" not in request.files or "width" not in request.form or "height" not in request.form:
        return jsonify({"error": "Provide files, width, and height"}), 400

    files = request.files.getlist("files")
    width = int(request.form["width"])
    height = int(request.form["height"])
    quality = int(request.form.get("quality", 85))

    temp_dir = tempfile.mkdtemp()
    output_files = []

    for f in files:
        img = Image.open(f)
        img = img.resize((width, height), Image.LANCZOS)
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png"]:
            ext = ".jpg"
        out_path = os.path.join(temp_dir, secure_filename(f.filename))
        if ext in [".jpg", ".jpeg"]:
            img.save(out_path, "JPEG", quality=quality, optimize=True)
        else:
            img.save(out_path, optimize=True)
        output_files.append(out_path)

    # ZIP multiple files
    zip_path = os.path.join(tempfile.gettempdir(), "resized_images.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for file in output_files:
            zipf.write(file, os.path.basename(file))
            os.remove(file)
    os.rmdir(temp_dir)

    return safe_send_file(zip_path, "resized_images.zip")

# ---------------- EXTRACT TEXT ----------------
@app.route("/extract-text", methods=["POST"])
def extract_text():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    uploaded = request.files["file"]
    fd, input_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    uploaded.save(input_path)

    try:
        reader = PdfReader(input_path)
        texts = []
        for p in reader.pages:
            try:
                texts.append(p.extract_text() or "")
            except Exception:
                texts.append("")  # continue if a page fails to extract
        out_txt = "\n\n".join(texts)
        out_path = os.path.join(tempfile.gettempdir(), secure_filename(uploaded.filename) + ".txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(out_txt)
        return safe_send_file(out_path, secure_filename(uploaded.filename).rsplit(".",1)[0] + ".txt")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)

# ---------------- PDF → IMAGES (zip) ----------------
@app.route("/pdf-to-images", methods=["POST"])
def pdf_to_images():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    uploaded = request.files["file"]
    fd, input_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    uploaded.save(input_path)

    dpi = int(request.form.get("dpi", 200))
    try:
        pages = convert_from_path(input_path, dpi=dpi)
    except Exception as e:
        if os.path.exists(input_path):
            os.remove(input_path)
        return jsonify({"error": "Conversion failed", "details": str(e)}), 500

    out_files = []
    for i, img in enumerate(pages, start=1):
        out_path = os.path.join(tempfile.gettempdir(), f"{secure_filename(uploaded.filename)}_page_{i}.png")
        img.save(out_path, "PNG")
        out_files.append(out_path)

    zip_path = _zip_files(out_files, zip_name=secure_filename(uploaded.filename) + "_images.zip")
    # cleanup page images
    for p in out_files:
        try: os.remove(p)
        except: pass
    if os.path.exists(input_path):
        os.remove(input_path)
    return safe_send_file(zip_path, secure_filename(uploaded.filename) + "_images.zip")

# ---------------- ROTATE PAGES ----------------
@app.route("/rotate", methods=["POST"])
def rotate_pdf():
    if "file" not in request.files or "angle" not in request.form:
        return jsonify({"error": "File and angle required"}), 400
    uploaded = request.files["file"]
    angle = int(request.form.get("angle", 90))  # expected 90/180/270

    fd, input_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    uploaded.save(input_path)

    try:
        reader = PdfReader(input_path)
        writer = PdfWriter()
        for p in reader.pages:
            try:
                p.rotate_clockwise(angle)
            except Exception:
                # best-effort: if rotate_clockwise not supported, try rotate
                try:
                    p.rotate(angle)
                except Exception:
                    pass
            writer.add_page(p)
        out_path = os.path.join(tempfile.gettempdir(), secure_filename(uploaded.filename).rsplit(".",1)[0] + f"_rotated_{angle}.pdf")
        with open(out_path, "wb") as f:
            writer.write(f)
        return safe_send_file(out_path, secure_filename(uploaded.filename).rsplit(".",1)[0] + f"_rotated_{angle}.pdf")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)

# ---------------- METADATA ----------------
@app.route("/metadata", methods=["POST"])
def metadata():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    uploaded = request.files["file"]
    reader = PdfReader(uploaded)
    meta = {}
    try:
        raw_meta = getattr(reader, "metadata", {}) or {}
        # normalize values to strings
        for k, v in raw_meta.items():
            meta[str(k)] = str(v)
    except Exception:
        meta = {}
    pages = len(reader.pages) if getattr(reader, "pages", None) is not None else 0
    return jsonify({"filename": secure_filename(uploaded.filename), "pages": pages, "metadata": meta})

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port)