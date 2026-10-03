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

def capacity_share(rho,alpha,gamma):
    """Unsaturated equilibrium with a relative capacity multiplier gamma."""
    a=3*rho*(1-gamma*(1-alpha));b=gamma+2-a
    s=2*gamma/(b+math.sqrt(b*b+4*a*gamma))
    if 3*rho*s>1:raise ValueError('unsaturated approximation outside domain')
    return s

def fixed_residual_share(budget_pp):
    """Equal capacities, active unclipped additive under-reporting budget."""
    x=budget_pp/100
    return (1+x)/(3+x)

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
