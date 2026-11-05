param([string] $Labels = 'scripts/replacement/labels-kanto.json')
$ErrorActionPreference = 'Stop'
$pythonPath = if ($env:IDEX_TRAIN_PYTHON) { $env:IDEX_TRAIN_PYTHON } else { 'python' }
function Invoke-Stage([string[]] $StageArguments) {
    Write-Output ("Starting " + ($StageArguments -join ' '))
    & $pythonPath @StageArguments --labels $Labels
    if ($LASTEXITCODE -ne 0) { throw "Stage failed with exit $LASTEXITCODE" }
}
Invoke-Stage -StageArguments @('scripts/replacement/train.py','predict','--arch','mobilenet_v3_large','--checkpoint','artifacts/replacement/runs/mobilenet224/best.pt','--split','val,ood_val','--out','artifacts/replacement/predictions/mobilenet-val.jsonl')
Invoke-Stage -StageArguments @('scripts/replacement/train.py','predict','--arch','efficientnet_b0','--checkpoint','artifacts/replacement/runs/efficientnet224/best.pt','--split','val,ood_val','--out','artifacts/replacement/predictions/efficientnet-val.jsonl')
Invoke-Stage -StageArguments @('scripts/replacement/metrics.py','summarize','--predictions','artifacts/replacement/predictions/mobilenet-val.jsonl','--output','artifacts/replacement/reports/mobilenet-val.json','--replicates','0')
Invoke-Stage -StageArguments @('scripts/replacement/metrics.py','summarize','--predictions','artifacts/replacement/predictions/efficientnet-val.jsonl','--output','artifacts/replacement/reports/efficientnet-val.json','--replicates','0')
Invoke-Stage -StageArguments @('scripts/replacement/train.py','train','--arch','efficientnet_b0','--init-checkpoint','artifacts/replacement/runs/efficientnet224/best.pt','--epochs','12','--lr','0.0001','--seed','20261035','--max-minutes','25','--out','artifacts/replacement/runs/efficientnet224-continued')
