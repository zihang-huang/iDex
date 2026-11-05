"""Deterministic group-only split with explicit low-support diagnostics."""
import random


def split_classes(rows, components, byclass, ids, seed=20261027, min_groups=5, rng=None):
    if min_groups < 3: raise ValueError('min-groups must be at least 3')
    rng=rng or random.Random(seed); counts={}; insufficient=[]
    for target in ids:
        keys=sorted(byclass.get(target, [])); rng.shuffle(keys)
        counts[target]=len(keys)
        if len(keys)<min_groups:
            insufficient.append(dict(id=target, groups=len(keys), required=min_groups,
                                     policy='train_only' if len(keys)<3 else 'one_per_split_minimum'))
        if len(keys)<3:
            for key in keys:
                for i in components[key]: rows[i]['split']='train'
            continue
        # Stable sort preserves the original seeded order when all sources have
        # equal priority. Prefer complete photographic/card groups for the test.
        def priority(key):
            return int(not any(rows[i].get('source') not in ('sprites','synthetic')
                               and not rows[i].get('synthetic', False) for i in components[key]))
        keys.sort(key=priority)
        ntest=max(1,round(len(keys)*.15)); nval=max(1,round(len(keys)*.15))
        for j,key in enumerate(keys):
            split='test_public' if j<ntest else 'val' if j<ntest+nval else 'train'
            for i in components[key]: rows[i]['split']=split
    return counts, insufficient
