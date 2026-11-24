"""Synthetic PDFs built at test time (no fixtures on disk)."""
import io
from pathlib import Path
from reportlab.lib.pagesizes import letter,landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from PIL import Image

def _png(width=600,height=800,color=(40,40,40)):
    buf=io.BytesIO();Image.new('RGB',(width,height),color).save(buf,format='PNG');buf.seek(0);return ImageReader(buf)

def make_pdf(path,pages,encrypt=None,labels=None):
    """pages: list of dicts: kind in text|image|ocr|blank|landscape, lines (for text/ocr)."""
    c=canvas.Canvas(str(path),pagesize=letter,encrypt=encrypt)
    if labels:
        for n,style,start in labels:c.addPageLabel(n,style,start)
    for page in pages:
        kind=page.get('kind','text')
        if kind=='landscape':c.setPageSize(landscape(letter))
        else:c.setPageSize(letter)
        w,h=c._pagesize
        if kind in ('image','ocr'):c.drawImage(_png(),0,0,width=w,height=h)
        if kind in ('text','landscape'):
            y=h-72
            for line in page.get('lines',[]):c.drawString(72,y,line);y-=14
        if kind=='ocr':
            t=c.beginText(72,h-72);t.setTextRenderMode(3)  # invisible text over a page image
            for line in page.get('lines',[]):t.textLine(line)
            c.drawText(t)
        c.showPage()
    c.save();return Path(path)

TEXT=['PUBLIC DISCLOSURE','August 12, 2015','COMMUNITY REINVESTMENT ACT','PERFORMANCE EVALUATION','Example State Bank','Certificate Number: 14807']
