"""Small synthetic regression test; never uses or modifies personal song PDFs."""
import importlib.util
from pathlib import Path
import pymupdf

builder_path = Path(__file__).with_name('build_songbook.py')
spec = importlib.util.spec_from_file_location('songbook_builder', builder_path)
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

def page_with_text(box):
    pdf = pymupdf.open()
    p = pdf.new_page(width=612, height=792)
    for k in range(9):
        p.insert_text((box[0], box[1]+k*box[2]), 'C      F      G      Am     Dm      G7      C', fontsize=box[3])
    return pdf

small = page_with_text((220, 270, 14, 8))
normal = page_with_text((65, 120, 55, 21))
short = pymupdf.open(); p=short.new_page(width=612,height=792); p.insert_text((200,390),'One last chord: C',fontsize=11)
for name, pdf, expected in [('small',small,True),('normal',normal,False),('continuation',short,False)]:
    pg=pdf[0]
    result=b.choose_source_clip(pg, b.source_page_ink_fraction(pg))
    print(f'{name}:', 'enlarge '+str(round(result[1],2)) if result else 'no enlargement')
    assert bool(result) == expected, name
    pdf.close()
print('PASS: small chart enlarged; normal and sparse continuation unchanged')
# Verify clipping is rendered as a complete magnified chart, not an empty page.
pdf = page_with_text((220, 270, 14, 8))
source_page = pdf[0]
clip, gain = b.choose_source_clip(source_page, b.source_page_ink_fraction(source_page))
out = pymupdf.open()
out_page = out.new_page(width=612, height=792)
out_page.show_pdf_page(b.BODY, pdf, 0, clip=clip, keep_proportion=True)
assert out_page.get_text().count('C      F') >= 1, 'scaled text lost in rendering'
assert out_page.get_text().count('G7') >= 8, 'source chart lines lost'
assert 1.18 <= gain <= 1.66
print('PASS: enlarged chart renders with all nine lines present')
out.close();pdf.close()

# Regression: a short *second* page with moderately dense typography must not
# expand just because its visible text sits in a compact block.
continuation = pymupdf.open()
continuation.new_page(width=612, height=792)
page = continuation.new_page(width=612, height=792)
for i in range(14):
    page.insert_text((155, 90 + i * 11), 'G Am C D7 Em C G', fontsize=10)
ratio = b.source_page_ink_fraction(page)
assert ratio >= 0.003, f'fixture too sparse to test vertical safeguard: {ratio:.4f}'
assert b.choose_source_clip(page, ratio) is None, 'short continuation was enlarged'
print('PASS: moderately dense short second page not enlarged')
continuation.close()

# A legitimate, undersized tall second page should still be eligible.
tall = pymupdf.open()
tall.new_page(width=612, height=792)
page = tall.new_page(width=612, height=792)
for i in range(35):
    page.insert_text((210, 90 + i * 14), 'C F G Am Dm G7 C', fontsize=8)
ratio = b.source_page_ink_fraction(page)
choice = b.choose_source_clip(page, ratio)
assert choice is not None, 'undersized full-height continuation incorrectly blocked'
print(f'PASS: tall undersized second page enlarged {choice[1]:.2f}x')
tall.close()
