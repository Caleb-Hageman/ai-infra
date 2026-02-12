from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

def is_pdf(file_path):
    try:
        with open(file_path, 'rb') as f:
            header = f.read(8)  # read first 8 bytes
            return header.startswith(b'%PDF-')
    except (IOError, OSError):
        return False

INPUT_FILE = "diabetes-clean.md"

if is_pdf(INPUT_FILE):
    reader = PdfReader(INPUT_FILE)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text() or ""
        text += page_text + "\n\n"   # keep paragraph-ish breaks

else:
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        text = f.read()


text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    length_function=len,
    separators=["\n\n", "\n", " ", ""],
    is_separator_regex=False,
    add_start_index=True,
)

chunks = text_splitter.create_documents([text])  # returns List[Document]

for i, doc in enumerate(chunks):
    print(f"Chunk {i+1} (length: {len(doc.page_content)}):\n{doc.page_content}\n") # Print chunk length and content
    print("-" * 60) # Separator chunks for readability
