"""Render manuscript equations for the standalone PDF, using mathtext."""
from pathlib import Path
import hashlib,json,re,os
R=Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR',str(R/'tmp/matplotlib'))
import matplotlib
matplotlib.use('Agg')
from matplotlib.mathtext import math_to_image
from matplotlib.font_manager import FontProperties
from PIL import Image
O=R/'tmp/pdfs/math';O.mkdir(parents=True,exist_ok=True)
def normalized(s):
    s=s.replace('\n',' ').strip()
    s=s.replace(r'{N_i^{successful\ CreateSMContext}\over\sum_jN_j^{successful\ CreateSMContext}}',
                r'\frac{N_i^{successful\ CreateSMContext}}{\sum_jN_j^{successful\ CreateSMContext}}')
    s=s.replace(r'{2\over3-a+\sqrt{(3-a)^2+4a}}',r'\frac{2}{3-a+\sqrt{(3-a)^2+4a}}')
    return s
def main():
    text=(R/'article/ARTICLE.md').read_text(encoding='utf-8')
    found=re.findall(r'\\\((.*?)\\\)|\\\[(.*?)\\\]',text,re.S)
    index={}
    for inline,display in found:
        latex=inline or display;key=hashlib.sha256(latex.encode()).hexdigest()[:16]
        path=O/(key+'.png')
        math_to_image('$'+normalized(latex)+'$',str(path),prop=FontProperties(size=11 if inline else 12),
                      dpi=260,format='png',color='black')
        with Image.open(path) as img:w,h=img.size
        index[latex]={'path':str(path),'width':w*72/260,'height':h*72/260}
    (O/'index.json').write_text(json.dumps(index,ensure_ascii=False),encoding='utf-8')
    print('Equation images:',len(index))
if __name__=='__main__':main()
