import os
import pymupdf4llm
import re
import logging
from modules.config.constants import *
import yaml
import json
from langchain_text_splitters import NLTKTextSplitter
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document

logger = logging.getLogger(__name__)

with open(config_bertopic_dir, "r") as file:
    config_bertopic = yaml.safe_load(file)
with open(config_chatbot_dir, "r") as file:
    config_chatbot = yaml.safe_load(file)

text_splitter_config = config_chatbot["text_splitter"]


def convert_pdfs_to_markdown(directory):
    # Get a list of all PDF files in the directory
    pdf_files = [
        os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".pdf")
    ]

    for pdf_file in pdf_files:
        # Create the path for the Markdown file
        markdown_file = os.path.splitext(pdf_file)[0] + ".md"

        # Check if the Markdown file already exists
        if os.path.exists(markdown_file):
            print(f"Skipping {pdf_file} as {markdown_file} already exists.")
            continue  # Skip this file if the Markdown file already exists

        # Convert the PDF to Markdown
        md_text = pymupdf4llm.to_markdown(pdf_file)

        # Write the markdown text to a file with the same name as the PDF
        with open(markdown_file, "w", encoding="utf-8") as output:
            output.write(md_text)
        print(f"Converted {pdf_file} to {markdown_file}.")


# Create an empty dictionary with the names of the markdown files
def create_empty_dict(directory):
    markdown_files = [f for f in os.listdir(directory) if f.endswith(".md")]
    result = {markdown_file: {} for markdown_file in markdown_files}
    return result


# Delete unwanted sections
def filter_sections(all_sections):
    # Compile regex patterns for unwanted headers, ensuring case-insensitivity
    unwanted_patterns = [
        re.compile(re.escape(text), re.IGNORECASE)
        for text in config_bertopic["unwanted_sections_header"]
    ]

    # Regex to capture section headers and bold text with newline following
    section_regex = re.compile(r"(#{1,6}\s+.*)|(\*\*.*?\*\*\s*\n)", re.IGNORECASE)

    # Filter out unwanted sections
    unwanted_sections = []
    for section in all_sections:
        # Search for headers or bold text followed by a newline
        match = section_regex.search(section)

        # Check if there's a match before trying to access group
        if match:
            header = match.group().strip()
            # Check against each pattern to see if the header matches an unwanted pattern
            if any(pattern.search(header) for pattern in unwanted_patterns):
                unwanted_sections.append(section)

    # Filter sections that are not unwanted
    filtered_sections = [
        section for section in all_sections if section not in unwanted_sections
    ]

    return filtered_sections


# Split markdown text by section
def split_markdown_by_section(markdown_text):
    # Delete figures and images
    markdown_text = re.sub(r"!\[.*?\]\(.*?\)", "", markdown_text)
    # Remove email addresses
    markdown_text = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "", markdown_text
    )
    # Remove Markdown-style links
    markdown_text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", markdown_text)
    # Remove standalone URLs (http/https)
    markdown_text = re.sub(r"\b(?:https?://)(?:\S|\s)+?(?=\s|$)", "", markdown_text)
    # Remove URLs starting with www.
    markdown_text = re.sub(r"\b(?:www\.)\S+\b", "", markdown_text)
    # Consolidate phrases
    phrase_mapping = config_bertopic["phrase_mapping"]
    for key, value in phrase_mapping.items():
        markdown_text = re.sub(
            r"\b" + re.escape(key) + r"\b", value, markdown_text, flags=re.IGNORECASE
        )

    # Split by markdown headers or bold text starting with a number or uppercase letter followed by a newline
    sections = re.split(
        r"(?<=\n)(#{1,6} .+?)(?=\n)|(?<=\n)(\*\*[A-Z0-9].+?\*\*)(?=\n)", markdown_text
    )

    # Filter out empty sections and strip whitespace
    sections = [section.strip() for section in sections if section]

    result = []
    current_section = ""

    # Combine headers or bold text with their following content
    for section in sections:
        if isinstance(section, str) and re.match(
            r"^(#{1,6} .+?|(\*\*[A-Z0-9].+?\*\*))$", section
        ):
            if current_section:
                result.append(current_section)
            current_section = section
        elif isinstance(section, str):
            current_section += "\n\n" + section

    if current_section:
        result.append(current_section)

    return result


def save_sections_to_list(directory):
    sections_list = []
    markdown_files = [
        os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".md")
    ]
    logging.info(f"Processing {len(markdown_files)} markdown files in {directory}")
    token_splitter = NLTKTextSplitter(chunk_size=5000)

    for markdown_file in markdown_files:
        try:
            with open(markdown_file, "r", encoding="utf-8") as file:
                markdown_text = file.read()
                sections = split_markdown_by_section(markdown_text)
                # Filter out unwanted sections based on headers
                filtered_sections = filter_sections(sections)
                # Filter out sections with fewer than 50 words
                filtered_sections = [
                    section
                    for section in filtered_sections
                    if len(section.split()) >= 50
                ]

                for section in filtered_sections:
                    chunks = token_splitter.split_text(section)
                    for chunk in chunks:
                        chunk = [Document(page_content=chunk, source="", page="")]
                        sections_list.extend(chunk)
                        print(chunk)
                        print(chunk[0].metadata)
                        exit()
            # result = {markdown_file: {}}

        except Exception as e:
            logging.error(f"Error processing file {markdown_file}: {e}")

    return sections_list


# Process all subfolders
def data_loader_subfolders(main_directory):
    all_sections = []
    subfolders = [
        os.path.join(main_directory, d)
        for d in os.listdir(main_directory)
        if os.path.isdir(os.path.join(main_directory, d))
    ]

    if not os.path.exists(f"data/documents-{docs_type}.json"):
        for subfolder in subfolders:
            logger.info(f"Loading data from {subfolder}")
            convert_pdfs_to_markdown(subfolder)
            sections = save_sections_to_list(subfolder)
            all_sections.extend(sections)

        with open(f"data/documents-{docs_type}.json", "w") as file:
            json.dump(all_sections, file)

    return all_sections


def process_pdf(folder_path):
    all_pages = []

    for filename in os.listdir(folder_path):
        if filename.endswith(".pdf"):
            file_path = os.path.join(folder_path, filename)

            loader = PyPDFLoader(file_path)
            pages = loader.load()

            all_pages.extend(pages)

    # Split the text of all pages
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=text_splitter_config["chunk_size"],
        chunk_overlap=text_splitter_config["chunk_overlap"],
        add_start_index=True,
    )

    all_splits = text_splitter.split_documents(all_pages)
    return all_splits
