import json
from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader


def is_pdf(file_path):
    """Check if a file is a PDF by examining its header."""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(8)
            return header.startswith(b'%PDF-')
    except (IOError, OSError):
        return False


def extract_text(file_path):
    """Extract text from a PDF or text file."""
    if not Path(file_path).exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if is_pdf(file_path):
        print(f"Detected PDF file: {file_path}")
        reader = PdfReader(file_path)
        text = ""
        for page_num, page in enumerate(reader.pages, 1):
            page_text = page.extract_text() or ""
            text += page_text + "\n\n"
        print(f"Extracted text from {len(reader.pages)} pages")
    else:
        print(f"Detected text file: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        print(f"Loaded {len(text)} characters")
    
    return text


def create_chunks(text, chunk_size=2000, chunk_overlap=200, file_type="markdown"):
    """Create text chunks using RecursiveCharacterTextSplitter."""
    # Choose separators based on file type
    separators = ["\n\n", "\n", ". ", " ", ""]
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=separators,
        is_separator_regex=False,
        add_start_index=True,
    )
    
    chunks = text_splitter.create_documents([text])
    print(f"Created {len(chunks)} chunks (size: {chunk_size}, overlap: {chunk_overlap})")
    
    return chunks


def enrich_metadata(chunks, source_file):
    """Add additional metadata to each chunk."""
    for i, doc in enumerate(chunks):
        doc.metadata['chunk_id'] = i
        doc.metadata['total_chunks'] = len(chunks)
        doc.metadata['source_file'] = source_file
        doc.metadata['chunk_length'] = len(doc.page_content)
    
    return chunks


def print_chunks(chunks, max_preview=200):
    """Print chunk information with preview."""
    print("\n" + "=" * 80)
    print("CHUNK PREVIEW")
    print("=" * 80)
    
    for i, doc in enumerate(chunks):
        print(f"\nChunk {i+1}/{len(chunks)}")
        print(f"Length: {doc.metadata['chunk_length']} chars")
        print(f"Start index: {doc.metadata.get('start_index', 'N/A')}")
        print(f"Preview: {doc.page_content[:max_preview]}...")
        print("-" * 80)


def save_chunks(chunks, output_file="chunks_output.json"):
    """Save chunks to JSON file."""
    output = [
        {
            "chunk_id": doc.metadata['chunk_id'],
            "text": doc.page_content,
            "metadata": doc.metadata
        }
        for doc in chunks
    ]
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Saved {len(chunks)} chunks to: {output_file}")


def main():
    """Main execution function."""
    # Configuration
    INPUT_FILE = "diabetes_clean.txt"
    OUTPUT_FILE = "chunks_output.json"
    CHUNK_SIZE = 2000          # Larger chunks for better context
    CHUNK_OVERLAP = 200
    SAVE_TO_FILE = True
    PRINT_PREVIEW = True
    MAX_PREVIEW_LENGTH = 2000   # Characters to show in preview
    
    try:
        # Step 1: Extract text
        print("\n Starting text chunking process...\n")
        text = extract_text(INPUT_FILE)
        
        if not text.strip():
            print("Warning: File is empty!")
            return
        
        # Step 2: Determine file type
        file_type = "markdown" if INPUT_FILE.endswith(('.md', '.markdown')) else "plain"
        
        # Step 3: Create chunks
        chunks = create_chunks(text, CHUNK_SIZE, CHUNK_OVERLAP, file_type)
        
        # Step 4: Enrich with metadata
        chunks = enrich_metadata(chunks, INPUT_FILE)
        
        # Step 5: Print preview
        if PRINT_PREVIEW:
            print_chunks(chunks, MAX_PREVIEW_LENGTH)
        
        # Step 6: Save to file
        if SAVE_TO_FILE:
            save_chunks(chunks, OUTPUT_FILE)
        
        # Summary statistics
        print("\n" + "=" * 80)
        print("SUMMARY STATISTICS")
        print("=" * 80)
        print(f"Input file: {INPUT_FILE}")
        print(f"Total text length: {len(text):,} characters")
        print(f"Number of chunks: {len(chunks)}")
        print(f"Average chunk size: {sum(len(c.page_content) for c in chunks) // len(chunks)} characters")
        print(f"Chunk size range: {min(len(c.page_content) for c in chunks)} - {max(len(c.page_content) for c in chunks)} characters")
        print("=" * 80)
        print("\n Process complete!\n")
        
    except FileNotFoundError as e:
        print(f"\n Error: {e}")
        print("Please check that the input file exists and the path is correct.")
    except Exception as e:
        print(f"\n Unexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()