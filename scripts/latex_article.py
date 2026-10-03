"""Self-contained LaTeX manuscript; external figures remain separate artifacts."""
from pathlib import Path
import re
R=Path(__file__).resolve().parents[1]
def esc(s):
    return ''.join({'&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_',
                    '{':r'\{','}':r'\}','~':r'\textasciitilde{}','^':r'\textasciicircum{}',
                    '\\':r'\textbackslash{}','→':r'\ensuremath{\to}','×':r'\ensuremath{\times}',
                    '≥':r'\ensuremath{\ge}','≤':r'\ensuremath{\le}','Δ':r'\ensuremath{\Delta}',
                    '…':r'\ldots{}','α':r'\ensuremath{\alpha}'} .get(c,c) for c in s)
def inline(s):
    pattern=r'(\\\(.*?\\\)|\[[^\]]+\]\([^\)]+\)|`[^`]+`|\*\*.*?\*\*)'
    out=[]
    for token in re.split(pattern,s):
        if token.startswith(r'\('):out.append(token)
        elif token.startswith('['):
            label,url=re.match(r'\[([^\]]+)\]\(([^\)]+)\)',token).groups()
            out.append(r'\href{'+url.replace('%',r'\%')+'}{'+esc(label)+'}')
        elif token.startswith('`'):
            value=token[1:-1]
            if len(value)>35:value=' '.join(value[i:i+25] for i in range(0,len(value),25))
            out.append(r'\texttt{'+esc(value)+'}')
        elif token.startswith('**'):out.append(r'\textbf{'+esc(token[2:-2])+'}')
        else:out.append(esc(token))
    return ''.join(out)
def main():
    lines=(R/'article/ARTICLE.md').read_text(encoding='utf-8').splitlines()
    body=[];i=0
    while i<len(lines):
        line=lines[i]
        if line==r'\[':
            j=lines.index(r'\]',i+1);body.extend(lines[i:j+1]);i=j+1;continue
        if line.startswith('|'):
            block=[]
            while i<len(lines) and lines[i].startswith('|'):
                cells=[c.strip() for c in lines[i].strip('|').split('|')]
                if not all(re.fullmatch('[-: ]+',c) for c in cells):block.append(cells)
                i+=1
            n=len(block[0]);width=(16.6-(n-1)*.28)/n
            body.append(r'{\footnotesize\setlength{\tabcolsep}{3pt}\renewcommand{\arraystretch}{1.25}')
            body.append(r'\begin{longtable}{'+''.join('p{'+str(round(width,2))+'cm}' for _ in range(n))+'}')
            body.append(r'\toprule')
            for k,row in enumerate(block):
                body.append(' & '.join(inline(c) for c in row)+r' \\')
                if k==0:body.append(r'\midrule\endhead')
            body.extend([r'\bottomrule\end{longtable}}']);continue
        if line.startswith('# '):
            title=re.sub(r'[:—]',' ',line[2:])
            body.extend([r'\title{'+esc(title)+'}',r'\author{}\date{}\maketitle'])
        elif line.startswith('### '):body.append(r'\subsection*{'+esc(line[4:])+'}')
        elif line.startswith('## '):body.append(r'\section*{'+esc(line[3:])+'}')
        elif re.match(r'^\d+\. ',line):body.append(r'\noindent '+inline(line)+r'\par')
        else:body.append(inline(line))
        i+=1
    preamble=r'''\documentclass[11pt,a4paper]{article}
\usepackage[T2A]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[russian]{babel}
\usepackage[margin=21mm]{geometry}
\usepackage{amsmath,amssymb,longtable,booktabs,array}
\usepackage[unicode,hidelinks]{hyperref}
\setlength{\parindent}{0pt}
\setlength{\parskip}{5pt}
\setlength{\emergencystretch}{3em}
\begin{document}
'''
    (R/'article/ARTICLE.tex').write_text(preamble+'\n'.join(body)+'\n\\end{document}\n',encoding='utf-8')
    print('LaTeX source updated')
if __name__=='__main__':main()
