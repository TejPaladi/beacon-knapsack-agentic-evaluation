# Overleaf package

`main.tex` is the submission-neutral LaTeX version of the working paper and
`main.pdf` is its locally compiled preview.

To use it in Overleaf:

1. create a blank project;
2. upload the contents of this directory; and
3. select `main.tex` as the main document with pdfLaTeX.

The source deliberately uses standard packages available in Overleaf. It does
not claim a conference format. If a venue is selected later, replace the
document class and bibliography style while keeping the study text, tables,
and citations.

The Markdown source of record remains `../paper_draft.md`. Regenerate the
LaTeX file after substantive paper edits, then compile twice so references and
table of contents are resolved.
