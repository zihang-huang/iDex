"""Small fixed-shape CNNs using installed torchvision only; normalization embedded."""
import hashlib
import json
from pathlib import Path
import torch
from torchvision import models
from labels import LABELS, read_labels, check_labels

SOURCE = Path('artifacts/replacement/sources')


class Classifier(torch.nn.Module):
    def __init__(self, backbone):
        super().__init__(); self.backbone=backbone
        self.register_buffer('mean',torch.tensor([.485,.456,.406]).reshape(1,3,1,1))
        self.register_buffer('std',torch.tensor([.229,.224,.225]).reshape(1,3,1,1))
    def forward(self,x): return self.backbone((x-self.mean)/self.std)


def make_model(arch, pretrained=False, num_classes=None, reference_weights=True, source=SOURCE):
    if num_classes is None: num_classes=len(read_labels())
    if type(num_classes) is not int or num_classes<2: raise ValueError('invalid class count')
    if arch=='baseline':
        if num_classes!=len(read_labels()): raise ValueError('Historical baseline label count mismatch')
        m=models.densenet121(num_classes=num_classes)
        if reference_weights:
            file=source/'BiernyVR--pokemon-classifier-mobilenetv3/pokemon_densenet121_best.pth'
            assert hashlib.sha256(file.read_bytes()).hexdigest()=='58e54044ed3ff747a26717313570e4c0b0f2204e7bdfcef7351d011861b2defe'
            state=torch.load(file,map_location='cpu',weights_only=True)
            m.load_state_dict(state.get('model_state_dict',state),strict=True)
    elif arch=='mobilenet_v3_large':
        m=models.mobilenet_v3_large()
        if pretrained:
            state=torch.load(source/'torchvision/mobilenet_v3_large-5c1a4163.pth',map_location='cpu',weights_only=True)
            m.load_state_dict(state,strict=True)
        m.classifier[-1]=torch.nn.Linear(m.classifier[-1].in_features,num_classes)
    elif arch=='efficientnet_b0':
        m=models.efficientnet_b0()
        if pretrained:
            state=torch.load(source/'torchvision/efficientnet_b0_rwightman-7f5810bc.pth',map_location='cpu',weights_only=True)
            m.load_state_dict(state,strict=True)
        m.classifier[-1]=torch.nn.Linear(m.classifier[-1].in_features,num_classes)
    else: raise ValueError(arch)
    return Classifier(m)


def load_checkpoint(file, labels=LABELS):
    checkpoint=torch.load(file,map_location='cpu',weights_only=True)
    expected=read_labels(labels)
    check_labels(checkpoint,expected)
    model=make_model(checkpoint['config']['arch'],num_classes=len(expected),reference_weights=False)
    model.load_state_dict(checkpoint['model'],strict=True)
    return model,checkpoint
