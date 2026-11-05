"""Online transparent-foreground compositing; all randomness is caller-owned."""
import io
import math
import random
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps


def has_transparency(image):
    return ('A' in image.getbands() or 'transparency' in image.info) and image.convert('RGBA').getextrema()[3][0] < 255


def augment(image, size=224, *, rng=None, backgrounds=()):
    """Return a fixed-size RGB synthetic image; opaque input is rejected."""
    if not has_transparency(image): raise ValueError('synthetic augmentation requires transparency')
    rng=rng or random
    color=lambda: tuple(rng.randrange(256) for _ in range(3))
    if backgrounds and rng.random()<.65:
        with Image.open(rng.choice(backgrounds)) as src:
            bg=ImageOps.exif_transpose(src).convert('RGB')
        side=min(bg.size); left=rng.randrange(bg.width-side+1); top=rng.randrange(bg.height-side+1)
        bg=bg.crop((left,top,left+side,top+side)).resize((size,size),Image.Resampling.BILINEAR)
    else:
        a,b=color(),color(); bg=Image.new('RGB',(size,size),a)
        if rng.random()<.5:
            draw=ImageDraw.Draw(bg)
            for y in range(size):
                draw.line((0,y,size,y),fill=tuple(round(x+(z-x)*y/max(1,size-1)) for x,z in zip(a,b)))
    fg=image.convert('RGBA'); box=fg.getbbox()
    if box: fg=fg.crop(box)
    span=max(1,round(size*rng.uniform(.35,.9)))
    scale=span/max(fg.size)
    fg=fg.resize((max(1,round(fg.width*scale)),max(1,round(fg.height*scale))),Image.Resampling.LANCZOS)
    fg=fg.rotate(rng.uniform(-15,15),Image.Resampling.BICUBIC,expand=True)
    # Mild projective denominator and shear, with a transparent fill.
    fg=fg.transform(fg.size,Image.Transform.PERSPECTIVE,
        (1,rng.uniform(-.06,.06),0,rng.uniform(-.06,.06),1,0,
         rng.uniform(-.0005,.0005),rng.uniform(-.0005,.0005)),Image.Resampling.BICUBIC)
    bg=bg.convert('RGBA')
    bg.alpha_composite(fg,(rng.randint(0,max(0,size-fg.width)),rng.randint(0,max(0,size-fg.height))))
    out=bg.convert('RGB')
    if rng.random()<.5: out=out.filter(ImageFilter.GaussianBlur(rng.uniform(.1,1.4)))
    out=ImageEnhance.Brightness(out).enhance(rng.uniform(.8,1.2))
    out=ImageEnhance.Contrast(out).enhance(rng.uniform(.8,1.2))
    warm=rng.uniform(-.10,.10)
    r,g,b=out.split(); r=r.point([min(255,max(0,round(i*(1+warm)))) for i in range(256)])
    b=b.point([min(255,max(0,round(i*(1-warm)))) for i in range(256)]); out=Image.merge('RGB',(r,g,b))
    if rng.random()<.12:
        draw=ImageDraw.Draw(out,'RGBA'); step=rng.randint(3,7); phase=rng.random()*math.tau
        for y in range(0,size,step):
            draw.line((0,y,size,y), fill=(0,0,0,round(8+5*math.sin(y*.15+phase))))
        for x in range(0,size,step): draw.line((x,0,x,size),fill=(255,255,255,10))
    buf=io.BytesIO(); out.save(buf,format='JPEG',quality=rng.randint(40,90)); buf.seek(0)
    with Image.open(buf) as decoded: return decoded.convert('RGB').copy()
