"""PDF typesetting of the final consolidated manuscript."""
import html,json,re
from pathlib import Path
from PIL import Image as PILImage
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,PageBreak,KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT=Path(__file__).resolve().parents[1]
for name,file in [('Body','times.ttf'),('Bold','timesbd.ttf'),('Italic','timesi.ttf'),('Head','arialbd.ttf')]:
    pdfmetrics.registerFont(TTFont(name,'C:/Windows/Fonts/'+file))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='Bold',italic='Italic',boldItalic='Bold')
styles={
    'body':ParagraphStyle('body',fontName='Body',fontSize=10.6,leading=13.5,spaceAfter=6,allowWidows=0,allowOrphans=0),
    'title':ParagraphStyle('title',fontName='Head',fontSize=18,leading=22,spaceAfter=14),
    'h1':ParagraphStyle('h1',fontName='Head',fontSize=12.7,leading=16,spaceBefore=8,spaceAfter=8,keepWithNext=True),
    'h2':ParagraphStyle('h2',fontName='Head',fontSize=10.8,leading=14,spaceBefore=7,spaceAfter=6,keepWithNext=True),
    'cell':ParagraphStyle('cell',fontName='Body',fontSize=8.8,leading=11),
    'caption':ParagraphStyle('caption',fontName='Italic',fontSize=9,leading=11.5,spaceAfter=9)}

def inline(text):
    text=text.replace('–','-').replace('—','-').replace('−','-').replace('₃','3')
    pieces=re.split(r'(\[[^\]]+\]\([^)]+\))',text);out=[]
    for part in pieces:
        m=re.fullmatch(r'\[([^\]]+)\]\(([^)]+)\)',part)
        out.append('<a color="#156a8a" href="'+html.escape(m[2],quote=True)+'">'+html.escape(m[1])+'</a>' if m else html.escape(part))
    return ''.join(out)

def footer(c,doc):
    c.setFont('Body',8);c.setFillColor(colors.HexColor('#777777'))
    c.drawString(48,25,'SMF / SCP: проверка достоверности нагрузки')
    c.drawRightString(A4[0]-48,25,str(doc.page))

def main():
    equations=json.loads((ROOT/'article/figures/final20261007/equations.json').read_text())
    lines=(ROOT/'article/ARTICLE_FINAL_20261007.md').read_text(encoding='utf-8').splitlines();story=[];i=0
    while i<len(lines):
        line=lines[i].strip();i+=1
        if not line:continue
        if line=='<!--pagebreak-->':story.append(PageBreak());continue
        if line.startswith('$$'):
            path=equations[line[2:-2]]
            with PILImage.open(path) as im:w,h=im.size
            width=min(490,w*72/250)
            story.append(KeepTogether([Spacer(1,4),Image(path,width=width,height=h*width/w),Spacer(1,8)]));continue
        if line.startswith('!['):
            caption,path=re.fullmatch(r'!\[(.*?)\]\((.*?)\)',line).groups();path=ROOT/'article'/path
            with PILImage.open(path) as im:w,h=im.size
            width=490
            story.append(KeepTogether([Image(str(path),width=width,height=h*width/w),Paragraph(inline(caption),styles['caption'])]));continue
        if line.startswith('|'):
            rows=[line]
            while i<len(lines) and lines[i].startswith('|'):rows.append(lines[i]);i+=1
            data=[]
            for row in rows:
                cells=[x.strip() for x in row.strip('|').split('|')]
                if all(re.fullmatch(r'[-: ]+',x) for x in cells):continue
                data.append([Paragraph(inline(x),styles['cell']) for x in cells])
            n=len(data[0]);widths={3:[290,104,105],4:[155,113,113,118],5:[135,75,98,95,96]}.get(n,[499/n]*n)
            table=Table(data,colWidths=widths,repeatRows=1)
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7eef1')),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#c9d2d6')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
            story.extend([table,Spacer(1,8)]);continue
        for prefix,style in [('### ','h2'),('## ','h1'),('# ','title')]:
            if line.startswith(prefix):story.append(Paragraph(inline(line[len(prefix):]),styles[style]));break
        else:story.append(Paragraph(inline(line),styles['body']))
    out=ROOT/'output/pdf/SMF_Load_Veracity_Final_20261007.pdf'
    SimpleDocTemplate(str(out),pagesize=A4,leftMargin=48,rightMargin=48,topMargin=40,bottomMargin=42,
        title='Независимая проверка нагрузки SMF с учётом округления и задержки',author='').build(story,onFirstPage=footer,onLaterPages=footer)
    print(out)

if __name__=='__main__':main()
