from flask import Flask, request, send_file, after_this_request, jsonify
from flask_cors import CORS
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
import tempfile, os, zipfile
from werkzeug.utils import secure_filename
import pikepdf
from pdf2docx import Converter
from docx2pdf import convert as docx_to_pdf
from PIL import Image
from flask import Flask, request, send_file, render_template
from flask_cors import CORS

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

@app.route('/')
def home():
    return render_template('test.html')  # your frontend

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
    output_path = input_path.replace(".docx", ".pdf")
    docx_to_pdf(input_path, output_path)

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
import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port)