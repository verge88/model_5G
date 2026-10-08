"""Prospective validation after selecting the existing quantized residual."""
import robustness_stage as engine

def plan():
    return [dict(stage='honest-cap70' if alpha==0 else 'attack-cap70',policy=policy,
                 rho=.5,seed=seed,alpha=alpha,extra=['--capacity3','70'])
            for seed in [501,502,503] for alpha in [0,.25] for policy in ['swrr','random']]

if __name__=='__main__':
    engine.STATE=engine.ROOT/'results/quantization-v1'
    engine.SERIES='quantization-v1'
    engine.plan=plan
    engine.main()
