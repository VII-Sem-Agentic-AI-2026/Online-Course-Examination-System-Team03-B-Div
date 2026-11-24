from backend.app.document_processing.text_extractor import (
    extract_text,
)

file_path = input("Enter the full path of your PPTX file: ").strip()

try:
    extracted_text = extract_text(file_path)

    print("\n========== EXTRACTION SUCCESSFUL ==========")
    print("Total characters:", len(extracted_text))
    print("\n========== EXTRACTED CONTENT ==========\n")

    print(extracted_text[:5000])

except Exception as error:
    print("\nEXTRACTION FAILED")
    print(error)