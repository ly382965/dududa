#!/usr/bin/env bash
set -euo pipefail

report_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$report_root/latex"
mkdir -p build "$report_root/pdf"

if [[ -n "${TECTONIC:-}" ]] || command -v tectonic >/dev/null 2>&1; then
  report_engine="${TECTONIC:-tectonic}"
  for report_name in design-report work-introduction; do
    "$report_engine" -X compile "$report_name.tex" -Z search-path=vendor \
      --keep-logs --keep-intermediates --outdir build
  done
else
  export TEXINPUTS="$report_root/latex/vendor:${TEXINPUTS:-}:"
  for report_name in design-report work-introduction; do
    if command -v latexmk >/dev/null 2>&1; then
      latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=build "$report_name.tex"
    elif command -v xelatex >/dev/null 2>&1; then
      xelatex -interaction=nonstopmode -halt-on-error -output-directory=build "$report_name.tex"
      (cd build && bibtex "$report_name")
      xelatex -interaction=nonstopmode -halt-on-error -output-directory=build "$report_name.tex"
      xelatex -interaction=nonstopmode -halt-on-error -output-directory=build "$report_name.tex"
    else
      printf '%s\n' 'Install Tectonic, or TeX Live with XeLaTeX, CTeX, Fandol, TikZ and BibLaTeX.' >&2
      exit 1
    fi
  done
fi

cp build/design-report.pdf "$report_root/pdf/01_设计文档.pdf"
cp build/work-introduction.pdf "$report_root/pdf/04_作品简介.pdf"
printf '%s\n' "$report_root/pdf/01_设计文档.pdf" "$report_root/pdf/04_作品简介.pdf"
