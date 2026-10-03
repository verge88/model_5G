"""Typeset the measured manuscript. Run with the bundled document Python."""
from pathlib import Path
import html,json,re
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image as PILImage

R=Path(__file__).resolve().parents[1]
M=json.loads((R/'tmp/pdfs/math/index.json').read_text(encoding='utf-8'))
for name,file in [('Body','times.ttf'),('BodyBold','timesbd.ttf'),('BodyItalic','timesi.ttf'),
                  ('Heading','arial.ttf'),('HeadingBold','arialbd.ttf')]:
    pdfmetrics.registerFont(TTFont(name,'C:/Windows/Fonts/'+file))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='BodyBold',italic='BodyItalic',boldItalic='BodyBold')
styles={
    'body':ParagraphStyle('body',fontName='Body',fontSize=10.5,leading=14.2,spaceAfter=6,allowWidows=0,allowOrphans=0),
    'title':ParagraphStyle('title',fontName='HeadingBold',fontSize=18,leading=22,spaceAfter=18),
    'h1':ParagraphStyle('h1',fontName='HeadingBold',fontSize=13,leading=17,spaceBefore=13,spaceAfter=7,keepWithNext=True),
    'h2':ParagraphStyle('h2',fontName='HeadingBold',fontSize=11,leading=14,spaceBefore=10,spaceAfter=6,keepWithNext=True),
    'cell':ParagraphStyle('cell',fontName='Body',fontSize=8.6,leading=11),
    'caption':ParagraphStyle('caption',fontName='BodyItalic',fontSize=9,leading=12,spaceAfter=9),
}
def inline(text):
    pieces=re.split(r'(\\\(.*?\\\)|\[[^\]]+\]\([^\)]+\)|`[^`]+`|\*\*.*?\*\*)',text)
    out=[]
    for token in pieces:
        if token.startswith(r'\('):
            m=M[token[2:-2]]
            out.append(f'<img src="{html.escape(m["path"])}" width="{m["width"]}" height="{m["height"]}" valign="middle"/>')
        elif token.startswith('['):
            label,url=re.match(r'\[([^\]]+)\]\(([^\)]+)\)',token).groups()
            out.append('<a href="'+html.escape(url,quote=True)+'">'+html.escape(label)+'</a>')
        elif token.startswith('`'):
            value=token[1:-1]
            if len(value)>45:value=' '.join(value[i:i+28] for i in range(0,len(value),28))
            out.append(html.escape(value))
        elif token.startswith('**'):out.append('<b>'+html.escape(token[2:-2])+'</b>')
        else:out.append(html.escape(token))
    return ''.join(out)
def footer(c,doc):
    c.saveState();c.setFont('Body',9);c.setFillColor(colors.HexColor('#555555'))
    c.drawCentredString(A4[0]/2,25,str(doc.page));c.restoreState()
def main():
    snap=json.loads((R/'article/figures/data-snapshot.json').read_text())
    audited=json.loads((R/'results/article-evaluation/audit.json').read_text())
    assert snap['runs']==[r['run'] for r in audited['runs'] if r['eligible']], 'Refresh figures before PDF'
    lines=(R/'article/ARTICLE.md').read_text(encoding='utf-8').splitlines()
    story=[];i=0;pending=None
    figure_map={'Эффект занижения нагрузки':('effect','Изменение доли атакующего SMF в парных опытах и стационарная модель'),
                'Дополнительные кампании':('adaptive','Наблюдаемые эффект и доля тревог в дополнительных кампаниях по одному запуску'),
                'Детекторы на отложенных тестовых запусках':('detectors','Измеренные FPR и Pd при порогах из отдельной честной калибровки'),
                'Распространение и свежесть отчётов':('timing','Квантили времени по отдельным пригодным запускам')}
    while i<len(lines):
        line=lines[i]
        if line==r'\[':
            j=lines.index(r'\]',i+1);latex='\n'+'\n'.join(lines[i+1:j])+'\n';m=M[latex]
            scale=min(1,490/m['width']);img=Image(m['path'],width=m['width']*scale,height=m['height']*scale)
            img.hAlign='CENTER';story.extend([Spacer(1,5),img,Spacer(1,9)]);i=j+1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].startswith('|'):
                cells=[c.strip() for c in lines[i].strip('|').split('|')]
                if not all(re.fullmatch('[-: ]+',c) for c in cells):rows.append(cells)
                i+=1
            n=len(rows[0]);widths={2:[120,379],3:[265,110,124],4:[220,83,90,106],
                                    5:[139,55,99,103,103],6:[73,55,35,72,165,99],
                                    7:[99,46,64,83,45,45,117]}.get(n,[499/n]*n)
            table=Table([[Paragraph(inline(c),styles['cell']) for c in row] for row in rows],
                        colWidths=widths,repeatRows=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e5e9ed')),
                       ('GRID',(0,0),(-1,-1),.35,colors.HexColor('#d0d0d0')),
                       ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),6),
                       ('BOTTOMPADDING',(0,0),(-1,-1),6),('LEFTPADDING',(0,0),(-1,-1),6),
                       ('RIGHTPADDING',(0,0),(-1,-1),6)]))
            story.extend([table,Spacer(1,8)])
            if pending:
                name,caption=pending;path=R/f'article/figures/{name}.png'
                with PILImage.open(path) as image:w,h=image.size
                story.append(KeepTogether([Image(str(path),width=485,height=485*h/w),
                                           Paragraph(caption,styles['caption'])]))
                pending=None
            continue
        if line.startswith('# '):
            story.append(Paragraph(inline(re.sub('[:—]',' ',line[2:])),styles['title']))
        elif line.startswith('### '):
            heading=line[4:];pending=figure_map.get(heading)
            story.append(Paragraph(inline(heading),styles['h2']))
        elif line.startswith('## '):story.append(Paragraph(inline(line[3:]),styles['h1']))
        elif line:story.append(Paragraph(inline(line),styles['body']))
        i+=1
    output=R/'output/pdf';output.mkdir(parents=True,exist_ok=True)
    path=output/'SMF_Load_Veracity.pdf'
    SimpleDocTemplate(str(path),pagesize=A4,rightMargin=48,leftMargin=48,topMargin=43,bottomMargin=43,
                      title='Фальсификация нагрузки SMF и независимая проверка через SCP',author='').build(story,onFirstPage=footer,onLaterPages=footer)
    print(path)
if __name__=='__main__':main()
