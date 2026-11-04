param([string] $Labels = 'iDex/Recognition/pokemon_labels.json')
$ErrorActionPreference = 'Stop'
$pythonPath = if ($env:IDEX_TRAIN_PYTHON) { $env:IDEX_TRAIN_PYTHON } else { 'python' }
function Invoke-Stage([string[]] $StageArguments) {
    Write-Output ("Starting " + ($StageArguments -join ' '))
    & $pythonPath @StageArguments --labels $Labels
    if ($LASTEXITCODE -ne 0) { throw "Stage failed with exit $LASTEXITCODE" }
}
if ($Labels -eq 'iDex/Recognition/pokemon_labels.json') {
    Invoke-Stage -StageArguments @('scripts/replacement/train.py','predict','--arch','baseline','--split','val,ood_val','--out','artifacts/replacement/predictions/baseline-val.jsonl')
}
Invoke-Stage -StageArguments @('scripts/replacement/train.py','train','--arch','mobilenet_v3_large','--epochs','8','--max-minutes','35','--out','artifacts/replacement/runs/mobilenet224')
Invoke-Stage -StageArguments @('scripts/replacement/train.py','train','--arch','efficientnet_b0','--epochs','8','--max-minutes','35','--out','artifacts/replacement/runs/efficientnet224')
