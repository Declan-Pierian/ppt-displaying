"""HTML template extraction and injection for token-optimized generation.

Instead of asking Claude to generate an entire HTML document (CSS + JS + toolbar +
navigation + slides), we separate the static boilerplate from the dynamic slide
content.  Claude only needs to generate the <div class="slide"> elements, and we
inject them into the pre-built template shell.  This cuts output tokens by ~50-60%.
"""

import os
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PLACEHOLDER = "<!-- SLIDES_PLACEHOLDER -->"

_REFERENCE_PATH = Path(__file__).parent / "reference_style.html"

# Storage root — same convention as config.py
_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "storage",
)
_CACHED_TEMPLATE_PATH = os.path.join(_STORAGE_DIR, "template_shell.html")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_template_shell(html: str) -> str | None:
    """Extract the static shell from an existing webpage.html.

    Finds all ``<div class="slide" ...>`` blocks inside the ``<div class="deck">``
    wrapper and replaces them with a single placeholder comment.  The returned
    string retains all CSS, JS, toolbar, navigation, safety-overrides, auto-fit
    and postMessage scripts — everything except the slide content.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # Find the deck container
    deck = soup.find("div", class_="deck") or soup.find("div", id="deck")
    if not deck:
        logger.warning("extract_template_shell: no .deck container found")
        return None

    # Find all slides inside the deck
    slides = deck.find_all("div", class_="slide", recursive=False)
    if not slides:
        # Try broader search — some generated HTMLs nest slides differently
        slides = deck.find_all("div", class_=re.compile(r"\bslide\b"))
    if not slides:
        logger.warning("extract_template_shell: no slides found inside deck")
        return None

    # Replace all slide divs with the placeholder
    for slide in slides:
        slide.decompose()

    # Insert the placeholder as raw text inside the deck
    from bs4 import Comment
    deck.append(Comment(" SLIDES_PLACEHOLDER "))

    result = str(soup)
    # BeautifulSoup renders the comment as <!--  SLIDES_PLACEHOLDER  -->
    # Normalise it to our exact marker
    result = re.sub(
        r"<!--\s*SLIDES_PLACEHOLDER\s*-->",
        _PLACEHOLDER,
        result,
    )

    if _PLACEHOLDER not in result:
        logger.warning("extract_template_shell: placeholder insertion failed")
        return None

    return result


def build_static_template(
    background_template_path: str | None = None,
    template_brightness: str = "dark",
) -> str:
    """Build a template shell from reference_style.html + safety CSS + JS.

    This is the fallback when no existing webpage.html exists to extract from.
    """
    if not _REFERENCE_PATH.exists():
        logger.error("reference_style.html not found at %s", _REFERENCE_PATH)
        return ""

    html = _REFERENCE_PATH.read_text(encoding="utf-8")

    # Replace the example slide with our placeholder
    # The reference_style.html has slides inside <div class="deck" id="deck">
    html = re.sub(
        r'(<div\s+class="deck"\s+id="deck">)\s*.*?(</div>\s*<script>)',
        rf"\1\n{_PLACEHOLDER}\n\2",
        html,
        count=1,
        flags=re.DOTALL,
    )

    if _PLACEHOLDER not in html:
        # Fallback: just replace the slide block
        html = re.sub(
            r'<div class="slide[^"]*"[^>]*>.*?</div>\s*(?=</div>\s*<script>)',
            f"\n{_PLACEHOLDER}\n",
            html,
            count=1,
            flags=re.DOTALL,
        )

    # Inject safety CSS before </head>
    safety_css = _build_safety_css(background_template_path, template_brightness)
    if "</head>" in html.lower():
        html = html.replace("</head>", safety_css + "\n</head>", 1)

    # Inject auto-fit JS and postMessage JS before </body>
    autofit_js = _get_autofit_js()
    postmessage_js = _get_postmessage_js()
    if "</body>" in html.lower():
        html = html.replace("</body>", autofit_js + postmessage_js + "\n</body>", 1)

    return html


def inject_slides(template: str, slides_html: str) -> str:
    """Replace the placeholder in a template shell with generated slide HTML."""
    if _PLACEHOLDER not in template:
        logger.error("inject_slides: template does not contain placeholder")
        return template
    return template.replace(_PLACEHOLDER, slides_html, 1)


def get_template() -> str | None:
    """Try to find or build a reusable template shell.

    Priority:
    1. Cached template on disk (storage/template_shell.html)
    2. Extract from any existing presentation's webpage.html
    3. Return None (caller should use full generation or build_static_template)
    """
    # 1. Check cache
    if os.path.exists(_CACHED_TEMPLATE_PATH):
        cached = Path(_CACHED_TEMPLATE_PATH).read_text(encoding="utf-8")
        if _PLACEHOLDER in cached:
            return cached

    # 2. Scan existing presentations for a webpage.html
    presentations_dir = os.path.join(_STORAGE_DIR, "presentations")
    if os.path.isdir(presentations_dir):
        for pres_id in sorted(os.listdir(presentations_dir), reverse=True):
            webpage_path = os.path.join(presentations_dir, pres_id, "webpage.html")
            if os.path.exists(webpage_path):
                try:
                    html = Path(webpage_path).read_text(encoding="utf-8")
                    shell = extract_template_shell(html)
                    if shell and _PLACEHOLDER in shell:
                        # Cache for future use
                        _cache_template(shell)
                        logger.info(
                            "Extracted and cached template from presentation %s",
                            pres_id,
                        )
                        return shell
                except Exception as e:
                    logger.warning("Failed to extract template from %s: %s", pres_id, e)
                    continue

    return None


def cache_template_from_webpage(webpage_path: str) -> None:
    """Extract and cache a template from a freshly generated webpage.html."""
    try:
        html = Path(webpage_path).read_text(encoding="utf-8")
        shell = extract_template_shell(html)
        if shell and _PLACEHOLDER in shell:
            _cache_template(shell)
            logger.info("Cached template from %s", webpage_path)
    except Exception as e:
        logger.warning("Failed to cache template from %s: %s", webpage_path, e)


def apply_background_to_template(
    template: str,
    background_template_path: str | None,
    template_brightness: str = "dark",
) -> str:
    """Update the safety-overrides <style> block in a template with new background CSS.

    If the template was cached from a presentation with a different background,
    we need to update the background CSS rules.
    """
    if not background_template_path or not os.path.exists(background_template_path):
        return template

    bg_name = os.path.basename(background_template_path)

    # Build the new background CSS rule
    if template_brightness == "light":
        overlay = "linear-gradient(rgba(255,255,255,0.15),rgba(255,255,255,0.15))"
    else:
        overlay = "linear-gradient(rgba(15,23,42,0.35),rgba(15,23,42,0.45))"

    new_bg_rule = (
        f'/* Force background template */\n'
        f'.slide{{\n'
        f'  background:none !important;\n'
        f"  background-image:{overlay},url('/api/v1/admin/background-templates/{bg_name}') !important;\n"
        f'  background-size:cover,cover !important;\n'
        f'  background-position:center center !important;\n'
        f'  background-repeat:no-repeat !important;\n'
        f'}}\n'
    )

    # Try to replace existing background rule in safety-overrides
    bg_pattern = re.compile(
        r'/\*\s*Force background template[^*]*\*/\s*\.slide\{[^}]*\}\s*',
        re.DOTALL,
    )
    if bg_pattern.search(template):
        template = bg_pattern.sub(new_bg_rule, template, count=1)
    else:
        # No existing bg rule — inject before closing </style> of safety-overrides
        template = template.replace(
            '</style>\n',
            new_bg_rule + '</style>\n',
            1,
        )

    # Update text color rules for brightness
    if template_brightness == "light":
        new_color = (
            'body,h1,h2,h3,h4,h5,h6,p,li,span,td,th,div,a,label,strong,em,b,i'
            '{color:#1e293b !important;}\n'
        )
    else:
        new_color = (
            'body,h1,h2,h3,h4,h5,h6,p,li,span,td,th,div,a,label,strong,em,b,i'
            '{color:#f1f5f9 !important;}\n'
        )

    # Replace existing text color rule
    color_pattern = re.compile(
        r'body,h1,h2,h3,h4,h5,h6,p,li,span,td,th,div,a,label,strong,em,b,i'
        r'\{color:#[0-9a-f]+ !important;\}\n',
    )
    if color_pattern.search(template):
        template = color_pattern.sub(new_color, template, count=1)

    return template


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cache_template(shell: str) -> None:
    """Write the template shell to disk for reuse."""
    os.makedirs(os.path.dirname(_CACHED_TEMPLATE_PATH), exist_ok=True)
    Path(_CACHED_TEMPLATE_PATH).write_text(shell, encoding="utf-8")


def _build_safety_css(
    background_template_path: str | None = None,
    template_brightness: str = "dark",
) -> str:
    """Build the safety-overrides <style> block (same rules as website_html_generator.py)."""
    if template_brightness == "light" and background_template_path:
        text_color_rule = (
            'body,h1,h2,h3,h4,h5,h6,p,li,span,td,th,div,a,label,strong,em,b,i'
            '{color:#1e293b !important;}\n'
        )
    else:
        text_color_rule = (
            'body,h1,h2,h3,h4,h5,h6,p,li,span,td,th,div,a,label,strong,em,b,i'
            '{color:#f1f5f9 !important;}\n'
        )

    bg_image_css = ""
    if background_template_path and os.path.exists(background_template_path):
        bg_name = os.path.basename(background_template_path)
        if template_brightness == "light":
            overlay = "linear-gradient(rgba(255,255,255,0.15),rgba(255,255,255,0.15))"
        else:
            overlay = "linear-gradient(rgba(15,23,42,0.35),rgba(15,23,42,0.45))"
        bg_image_css = (
            f'/* Force background template */\n'
            f'.slide{{\n'
            f'  background:none !important;\n'
            f"  background-image:{overlay},url('/api/v1/admin/background-templates/{bg_name}') !important;\n"
            f'  background-size:cover,cover !important;\n'
            f'  background-position:center center !important;\n'
            f'  background-repeat:no-repeat !important;\n'
            f'}}\n'
        )

    return (
        '\n<style id="safety-overrides">\n'
        + text_color_rule
        + bg_image_css
        + '.tag,.pill,.badge,.kpi-label,.metric-mini .label,.chart-bar span'
        '{color:inherit !important;}\n'
        '.gradient-text{-webkit-text-fill-color:transparent !important;'
        'background-clip:text !important;}\n'
        '/* === STRICT SLIDE CONTAINMENT === */\n'
        '.slide,.slide-container{\n'
        '  overflow:hidden !important;max-height:100vh !important;height:100vh !important;\n'
        '  width:100vw !important;position:absolute !important;box-sizing:border-box !important;\n'
        '}\n'
        '.slide *{box-sizing:border-box !important;}\n'
        '.zoom-wrapper,.slide-content,.slide>[class*="content"],.slide>[class*="wrapper"],.slide>div{\n'
        '  max-height:100vh !important;overflow:hidden !important;box-sizing:border-box !important;\n'
        '}\n'
        '.zoom-wrapper,.slide-content,.slide>[class*="content"],.slide>[class*="wrapper"]{\n'
        '  padding:50px 90px !important;\n'
        '}\n'
        '.slide h1{font-size:clamp(1.3rem,3.2vw,2.5rem) !important;line-height:1.1 !important;margin-bottom:0.3em !important;}\n'
        '.slide h2{font-size:clamp(1rem,2.5vw,1.8rem) !important;line-height:1.15 !important;margin-bottom:0.25em !important;}\n'
        '.slide h3{font-size:clamp(0.9rem,2vw,1.3rem) !important;line-height:1.2 !important;margin-bottom:0.2em !important;}\n'
        '.slide p,.slide li{font-size:clamp(0.7rem,1.2vw,0.95rem) !important;line-height:1.3 !important;margin-bottom:0.25em !important;}\n'
        '.slide>*,.zoom-wrapper>*{max-width:100% !important;}\n'
        '.slide [style*="display:grid"]:not(.team-grid):not(.people-grid),'
        '.slide [style*="display: grid"]:not(.team-grid):not(.people-grid){\n'
        '  grid-template-columns:repeat(auto-fit,minmax(180px,1fr)) !important;\n'
        '  max-height:60vh !important;overflow:hidden !important;gap:14px !important;\n'
        '}\n'
        '.slide [style*="display:flex"],.slide [style*="display: flex"]{\n'
        '  max-height:70vh !important;overflow:hidden !important;max-width:100% !important;\n'
        '}\n'
        '.slide [class*="card"]:not(.person-card),.slide [class*="Card"]:not(.person-card),'
        '.slide [class*="feature"],.slide [class*="Feature"],'
        '.slide [class*="box"],.slide [class*="Box"],'
        '.slide [class*="service"],.slide [class*="Service"],.slide [class*="benefit"],.slide [class*="Benefit"],'
        '.slide [class*="cta"],.slide [class*="CTA"],.slide [class*="action"],.slide [class*="Action"]{\n'
        '  max-height:25vh !important;overflow:hidden !important;\n'
        '  padding:clamp(10px,1.5vh,20px) clamp(12px,1.5vw,24px) !important;\n'
        '}\n'
        '.slide img[src*="/api/v1/media/"]{\n'
        '  max-width:38vw !important;max-height:36vh !important;\n'
        '  width:auto !important;height:auto !important;object-fit:contain !important;border-radius:12px;\n'
        '}\n'
        '.slide .two-col>*:first-child{overflow:hidden !important;min-width:0 !important;max-width:55% !important;flex:1 1 55% !important;}\n'
        '.slide .two-col>*:last-child{max-width:42% !important;flex:0 0 38% !important;display:flex !important;align-items:center !important;justify-content:center !important;}\n'
        '.slide .two-col img[src*="/api/v1/media/"]{max-height:36vh !important;max-width:90% !important;width:auto !important;height:auto !important;object-fit:contain !important;display:block !important;margin:0 auto !important;}\n'
        '.slide img[src^="http"]:not([src*="/api/v1/"]){max-width:200px !important;max-height:200px !important;object-fit:cover !important;display:block !important;}\n'
        '.slide .team-photo,.slide .person-photo,.slide img[style*="border-radius: 50%"],.slide img[style*="border-radius:50%"]{\n'
        '  width:120px !important;height:120px !important;max-width:120px !important;max-height:120px !important;\n'
        '  object-fit:cover !important;flex-shrink:0 !important;border-radius:50% !important;\n'
        '}\n'
        '.slide .team-grid,.slide .people-grid{display:grid !important;grid-template-columns:repeat(auto-fill,minmax(140px,1fr)) !important;gap:20px !important;max-height:75vh !important;overflow:hidden !important;width:100% !important;max-width:100% !important;}\n'
        '.slide .team-grid>*,.slide .people-grid>*{max-width:100% !important;overflow:hidden !important;text-align:center !important;}\n'
        '.slide .person-card{display:flex !important;flex-direction:column !important;align-items:center !important;gap:6px !important;padding:8px !important;max-height:none !important;overflow:visible !important;}\n'
        '.slide .person-card .person-name{font-weight:600 !important;font-size:clamp(0.65rem,1vw,0.85rem) !important;line-height:1.2 !important;text-align:center !important;}\n'
        '.slide .person-card .person-role{font-size:clamp(0.55rem,0.8vw,0.7rem) !important;opacity:0.7 !important;text-align:center !important;}\n'
        '.slide ul,.slide ol{max-height:45vh !important;overflow:hidden !important;}\n'
        '.slide ul>li:nth-child(n+5),.slide ol>li:nth-child(n+5){display:none !important;}\n'
        '.slide table{max-height:50vh !important;overflow:hidden !important;font-size:clamp(0.65rem,1vw,0.85rem) !important;}\n'
        '.nav-zone{transition:opacity 0.3s ease !important;opacity:1 !important;}\n'
        '.nav-zones-hidden .nav-zone{opacity:0 !important;}\n'
        '.nav-zones-hidden .nav-zone:hover{opacity:1 !important;pointer-events:auto !important;}\n'
        '</style>\n'
    )


def _get_autofit_js() -> str:
    """Return the auto-fit JavaScript snippet."""
    return r"""
<script>
function autoFitSlides(){
  document.querySelectorAll('.slide').forEach(function(slide){
    var w = slide.querySelector('.zoom-wrapper')
         || slide.querySelector('.slide-content')
         || slide.querySelector('[class*="content"]')
         || slide.querySelector('[class*="wrapper"]');
    if(!w){
      var children = slide.children;
      for(var i=0;i<children.length;i++){
        var c=children[i];
        if(c.tagName==='DIV' && !c.classList.contains('nav-zone')
           && !c.classList.contains('nav-prev') && !c.classList.contains('nav-next')
           && c.className.indexOf('nav')===-1 && c.offsetHeight>50){
          w=c;break;
        }
      }
    }
    if(!w)return;
    w.style.transform='';
    w.style.transformOrigin='top left';
    var prevOverflow=slide.style.overflow;
    var prevWOverflow=w.style.overflow;
    slide.style.overflow='visible';
    w.style.overflow='visible';
    var sh=window.innerHeight;
    var sw=window.innerWidth;
    var wh=w.scrollHeight;
    var ww=w.scrollWidth;
    slide.style.overflow=prevOverflow||'';
    w.style.overflow=prevWOverflow||'';
    var scaleH = wh > sh*0.90 ? (sh*0.86)/wh : 1;
    var scaleW = ww > sw*0.95 ? (sw*0.90)/ww : 1;
    var scale = Math.min(scaleH, scaleW);
    if(scale < 0.98){
      scale = Math.max(0.30, scale);
      w.style.transform='scale('+scale+')';
      w.style.transformOrigin='top left';
      w.style.width=(100/scale)+'%';
    }
    slide.style.overflow='hidden';
  });
}
window.addEventListener("load",function(){
  setTimeout(autoFitSlides,200);
  setTimeout(autoFitSlides,600);
  setTimeout(autoFitSlides,1500);
  setTimeout(autoFitSlides,3000);
});
window.addEventListener("resize",function(){setTimeout(autoFitSlides,150);});

(function(){
  var alwaysVisible=true;
  var eyeSvgOpen='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
  var eyeSvgClosed='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>';
  function getAllNavZones(){
    var zones=[];
    document.querySelectorAll('.nav-zone,.nav-prev,.nav-next,[class*="nav-prev"],[class*="nav-next"]').forEach(function(el){zones.push(el);});
    document.querySelectorAll('[style*="left:0"][style*="height:100"],[style*="right:0"][style*="height:100"]').forEach(function(el){
      if(el.querySelector('svg')||el.textContent.trim().match(/^[<>←→‹›❮❯]$/)){zones.push(el);}
    });
    return zones;
  }
  function applyNavState(){
    var zones=getAllNavZones();
    if(alwaysVisible){document.body.classList.remove('nav-zones-hidden');zones.forEach(function(el){el.style.opacity='';el.style.pointerEvents='';});}
    else{document.body.classList.add('nav-zones-hidden');zones.forEach(function(el){el.style.opacity='';el.style.pointerEvents='';});}
  }
  function initEyeToggle(){
    var toolbar=document.querySelector('.toolbar,[class*="toolbar"],[id*="toolbar"]');
    if(!toolbar){
      var allFixed=document.querySelectorAll('[style*="position:fixed"],[style*="position: fixed"]');
      allFixed.forEach(function(el){if(el.offsetTop>window.innerHeight*0.7&&el.querySelectorAll('button').length>=2){toolbar=el;}});
    }
    if(!toolbar)return;
    var sep=document.createElement('span');
    sep.style.cssText='width:1px;height:20px;background:rgba(255,255,255,0.2);margin:0 4px;display:inline-block;vertical-align:middle;';
    var btn=document.createElement('button');
    btn.title='Toggle navigation arrows';
    btn.innerHTML=eyeSvgOpen;
    btn.style.cssText='background:rgba(255,255,255,0.1);border:none;color:#e2e8f0;cursor:pointer;padding:6px 8px;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;transition:all 0.2s;vertical-align:middle;';
    btn.addEventListener('mouseenter',function(){btn.style.background='rgba(255,255,255,0.2)';});
    btn.addEventListener('mouseleave',function(){btn.style.background=alwaysVisible?'rgba(255,255,255,0.1)':'rgba(239,68,68,0.2)';});
    btn.addEventListener('click',function(){
      alwaysVisible=!alwaysVisible;applyNavState();
      btn.innerHTML=alwaysVisible?eyeSvgOpen:eyeSvgClosed;
      btn.style.background=alwaysVisible?'rgba(255,255,255,0.1)':'rgba(239,68,68,0.2)';
    });
    toolbar.appendChild(sep);toolbar.appendChild(btn);applyNavState();
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',function(){setTimeout(initEyeToggle,500);});}
  else{setTimeout(initEyeToggle,500);}
})();
</script>
"""


def _get_postmessage_js() -> str:
    """Return the postMessage JS snippet for iframe sync."""
    return r"""
<script>
(function(){
  var lastSlide=-1;
  function notifyParent(){
    var idx=-1;
    if(typeof currentSlide!=='undefined') idx=currentSlide;
    else if(typeof currentIndex!=='undefined') idx=currentIndex;
    else {
      var slides=document.querySelectorAll('.slide');
      slides.forEach(function(s,i){if(s.classList.contains('active')){idx=i;}});
      if(idx<0){slides.forEach(function(s,i){var st=window.getComputedStyle(s);if(st.opacity==='1'&&st.display!=='none'&&st.visibility!=='hidden'){idx=i;}});}
    }
    if(idx!==lastSlide&&idx>=0){
      lastSlide=idx;
      var total=document.querySelectorAll('.slide').length;
      try{window.parent.postMessage({type:'slideChange',slideIndex:idx,totalSlides:total},'*');}catch(e){}
    }
  }
  setInterval(notifyParent,300);
  document.addEventListener('keydown',function(){setTimeout(notifyParent,100);});
  document.addEventListener('click',function(){setTimeout(notifyParent,200);});
  document.addEventListener('touchend',function(){setTimeout(notifyParent,200);});
})();
</script>
"""
