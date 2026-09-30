"""Analytical predictions only; output explicitly labelled, not measured data."""
import csv
import math
from pathlib import Path

def stationary_share(rho, alpha):
    # s[3 - 3*rho + 3*rho*alpha*s] = 1 - 3*rho*(1-alpha)*s
    a=3*rho*alpha
    s=1/3 if a==0 else 2/(3-a+math.sqrt((3-a)**2+4*a))
    if 3*rho*s > 1:
        raise ValueError('unsaturated approximation outside domain')
    return s

if __name__=='__main__':
    out=Path(__file__).resolve().parents[1]/'results/theory'
    out.mkdir(parents=True,exist_ok=True)
    with (out/'equilibrium.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['source','rho','alpha','honest_share','attack_share','delta_pp'])
        writer.writeheader()
        for alpha in [.1,.3,.5]:
            for rho in [.2,.5,.7]:
                s=stationary_share(rho,alpha)
                writer.writerow(dict(source='analytical_not_measured',rho=rho,alpha=alpha,
                    honest_share=1/3,attack_share=s,delta_pp=100*(s-1/3)))
