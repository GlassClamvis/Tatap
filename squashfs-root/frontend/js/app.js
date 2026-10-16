var cur = {slug:"", title:"", ep:1, mode:"sub", quality:"best", res:null, eps:[], watched:{},
            subLang:"English",    // preferensi bahasa user dari /api/settings
            activeSub:null,       // URL track subtitle yang sedang aktif (live switch)
            cues:[],              // cue subtitle hasil parse VTT (render overlay milik app)
            subSize:"m",          // ukuran subtitle overlay: s|m|l
            translate:false        // toggle translate subtitle Indonesia (persist localStorage)
           };
function $(id){return document.getElementById(id);}
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
function toast(msg,ms){
  $("toast-msg").textContent=msg;
  $("toast").classList.remove("hidden");
  clearTimeout(window._toastT);
  window._toastT=setTimeout(function(){$("toast").classList.add("hidden");},ms||2200);
}
// Anti-popup guard untuk pemutar video pihak ketiga
var _origOpen = window.open;
window.open = function(url, target, features){
  if(url && (String(url).indexOf("github.com") >= 0 || String(url).indexOf("127.0.0.1") >= 0)){
    return _origOpen ? _origOpen.apply(window, arguments) : null;
  }
  console.warn("[Tatap Anti-Ad] Popup diblokir:", url);
  return null;
};
function loadPrefs(){
  try{
    if(localStorage.getItem("tatap_crt")==="off"){document.body.classList.add("no-crt");}
    if(localStorage.getItem("tatap_ambient")==="off"){document.body.classList.add("no-ambient");}
  }catch(e){}
}

function openTitle(slug,title){
  cur.slug=slug;cur.title=title;cur.eps=[];
  if(slug && slug.startsWith("rebahin:")){
    cur.source = "rebahin";
    $("tm-eyebrow").textContent="DETAIL FILM / SERIES (REBAHIN)";
  } else if(slug && slug.startsWith("dutamovie:")){
    cur.source = "dutamovie";
    $("tm-eyebrow").textContent="DETAIL FILM / SERIAL (DUTAMOVIE21)";
  } else if(slug && slug.startsWith("otakudesu:")){
    cur.source = "otakudesu";
    $("tm-eyebrow").textContent="DETAIL ANIME (OTAKUDESU)";
  } else if(slug && (slug.startsWith("movie:") || slug.startsWith("series:") || slug.startsWith("film:"))){
    cur.source = "film";
    $("tm-eyebrow").textContent="DETAIL FILM / SERIAL (CINEMETA)";
  } else {
    $("tm-eyebrow").textContent="DETAIL ANIME";
  }
  renderSourceUI();
  $("tm-title").textContent=title;
  $("tm-sub").textContent=slug;
  $("tm-count").textContent="memuat...";
  $("tm-eps").innerHTML="";
  $("ep-filter").value="";
  var sBar=$("tm-seasons");if(sBar)sBar.classList.add("hidden");
  var sChips=$("tm-seasons-chips");if(sChips)sChips.innerHTML="";
  $("title-modal").classList.remove("hidden");
  loadEps();
  loadRelations();
}
function loadRelations(){
  var thisSlug=cur.slug;
  window.Tatap.relations(thisSlug, cur.title).then(function(r){
    if(thisSlug!==cur.slug)return; // Stale modal
    var sBar=$("tm-seasons");
    var sChips=$("tm-seasons-chips");
    if(!sBar||!sChips)return;
    if(!r||!r.success||!r.data||!r.data.relations||!r.data.relations.length){
      sBar.classList.add("hidden");
      return;
    }
    var rels=r.data.relations;
    sChips.innerHTML="";
    var count=0;
    for(var i=0;i<rels.length;i++){
      (function(rel){
        if(!rel.slug)return; // Lewati jika belum termap ke sumber video
        count++;
        var b=document.createElement("button");
        var cls="season-chip";
        var icon="📺";
        if(rel.relation==="PREQUEL"){cls+=" prequel";icon="⏮";}
        else if(rel.relation==="SEQUEL"){cls+=" sequel";icon="⏭";}
        else if(rel.format==="MOVIE"){cls+=" movie";icon="🎬";}
        b.className=cls;
        b.title=rel.title+(rel.year?" ("+rel.year+")":"");
        b.innerHTML="<span>"+icon+"</span> <b>"+rel.label+"</b>: "+esc(rel.title);
        b.addEventListener("click",function(e){
          if(e)e.stopPropagation();
          openTitle(rel.slug,rel.title);
        });
        sChips.appendChild(b);
      })(rels[i]);
    }
    if(count>0){
      sBar.classList.remove("hidden");
    }else{
      sBar.classList.add("hidden");
    }
  }).catch(function(){
    var sBar=$("tm-seasons");if(sBar)sBar.classList.add("hidden");
  });
}
var _epsMemCache = {};
cur.activeEpRange = null;

function renderEpRanges(){
  var bar = $("tm-ep-ranges");
  if(!bar) return;
  if(!cur.eps || cur.eps.length <= 100){
    bar.innerHTML = "";
    bar.classList.add("hidden");
    cur.activeEpRange = null;
    return;
  }
  bar.innerHTML = "";
  bar.classList.remove("hidden");
  var total = cur.eps.length;
  var step = 100;
  var lastWatchedEp = -1;
  if(cur.watched){
    for(var w in cur.watched){
      var n = parseInt(w);
      if(n > lastWatchedEp) lastWatchedEp = n;
    }
  }

  var ranges = [];
  for(var s = 1; s <= total; s += step){
    var e = Math.min(s + step - 1, total);
    ranges.push({start: s, end: e, label: s + " - " + e});
  }
  ranges.push({start: 1, end: total, label: "Semua (" + total + ")", isAll: true});

  if(!cur.activeEpRange){
    cur.activeEpRange = ranges[0];
    if(lastWatchedEp > 0){
      for(var r = 0; r < ranges.length - 1; r++){
        if(lastWatchedEp >= ranges[r].start && lastWatchedEp <= ranges[r].end){
          cur.activeEpRange = ranges[r];
          break;
        }
      }
    }
  }

  ranges.forEach(function(rng){
    var btn = document.createElement("button");
    btn.className = "ep-range-chip" + (cur.activeEpRange && cur.activeEpRange.label === rng.label ? " active" : "");
    btn.textContent = rng.label;
    btn.addEventListener("click", function(){
      cur.activeEpRange = rng;
      renderEpRanges();
      renderEpGrid();
    });
    bar.appendChild(btn);
  });
}

function loadEps(){
  cur.activeEpRange = null;
  var cached = _epsMemCache[cur.slug];
  if(cached){
    cur.eps = cached;
    $("tm-count").textContent = cur.eps.length + " episode · " + cur.mode.toUpperCase();
    renderEpRanges();
    renderEpGrid();
  }

  window.Tatap.episodes(cur.slug).then(function(r){
    if(!r.success){
      if(!cached) $("tm-count").textContent = "error: " + r.error;
      return;
    }
    cur.eps = r.data.episodes || [];
    _epsMemCache[cur.slug] = cur.eps;
    var watched = {};
    window.Tatap.history().then(function(h){
      (h.data || []).forEach(function(x){ if(x.slug === cur.slug) watched[x.episode] = 1; });
      cur.watched = watched;
      $("tm-count").textContent = cur.eps.length + " episode · " + cur.mode.toUpperCase();
      renderEpRanges();
      renderEpGrid();
    }).catch(function(){
      renderEpRanges();
      renderEpGrid();
    });
  });
}

function renderEpGrid(){
  var f = $("ep-filter").value.trim();
  var box = $("tm-eps");
  box.innerHTML = "";
  var shown = 0;
  var frag = document.createDocumentFragment();

  var epsToRender = cur.eps || [];
  var useRange = !f && cur.activeEpRange && !cur.activeEpRange.isAll;

  for(var i = 0; i < epsToRender.length; i++){
    var epObj = epsToRender[i];
    var ep = epObj.ep;
    if(f && String(ep).indexOf(f) < 0) continue;
    if(useRange && (ep < cur.activeEpRange.start || ep > cur.activeEpRange.end)) continue;

    shown++;
    var b = document.createElement("button");
    b.className = "ep" + (cur.watched && cur.watched[ep] ? " watched" : "");
    b.textContent = ep;
    (function(targetEp){
      b.addEventListener("click", function(e){
        if(e) e.stopPropagation();
        openPlayer(targetEp);
      });
    })(ep);
    frag.appendChild(b);
  }

  if(shown > 0){
    box.appendChild(frag);
  } else {
    box.innerHTML = "<p class='dim'>Tidak ada episode cocok filter.</p>";
  }
}
function closeTitle(){$("title-modal").classList.add("hidden");}
function syncSeg(){
  document.querySelectorAll("#mode-seg button").forEach(function(x){x.classList.toggle("active",x.getAttribute("data-mode")===cur.mode);});
}

function openPlayer(ep, resumeTime){
  cur.ep=ep;
  cur.playerOpenedAt=Date.now();
  closeTitle();
  $("player-modal").classList.remove("hidden");
  $("pm-title").textContent=cur.title;
  $("pm-meta").textContent="ep "+ep+" · "+cur.mode.toUpperCase();
  $("pm-spinner").classList.remove("hidden");
  $("pm-status").textContent="resolving ep "+ep+"...";
  updatePrevNext();
  var t0=Date.now();
  var src=cur.source||"";
  window.Tatap.resolve(cur.slug,ep,cur.mode,cur.quality,src).then(function(r){
    if(!r || !r.success){
      $("pm-spinner").classList.add("hidden");
      $("pm-status").textContent="ERROR: "+(r && r.error ? r.error : "gagal resolve stream");
      toast("Gagal resolve stream: "+(r && r.error ? r.error : "unknown"));
      return;
    }
    cur.res=r.data;
    cur.source=r.data.source||"hianime";
    var picked=r.data.picked||(r.data.variants&&r.data.variants[0])||{q:"HD",url:r.data.master||""};
    var srvText=r.data.server||"";
    $("pm-meta").innerHTML="ep "+ep+" · "+cur.mode.toUpperCase()+" · "+picked.q+" · <button id='pm-source-btn' class='server-badge' title='Klik untuk switch sumber' style='background:none;border:1px solid rgba(255,255,255,0.25);color:var(--cyan,#00dbeb);cursor:pointer;border-radius:4px;padding:1px 6px;font:inherit;'>"+esc(srvText)+" ⇄</button>"+(r.data.cached?" · cached":" · "+(Date.now()-t0)+"ms");
    var srvBtn=$("pm-source-btn");
    if(srvBtn){
      srvBtn.onclick=function(){
        if(window.Tui&&window.Tui.switchSource){window.Tui.switchSource();}
        else{App.switchSource();}
      };
    }
    renderVariants();
    // Render dropdown subtitle: pilih track yang cocok dengan preferensi user
    // (cur.subLang) atau default: true. Simpan URL track yang aktif.
    cur.activeSub = pickSubtitleUrl(r.data.subtitles || [], cur.subLang);
    renderSubtitles(r.data.subtitles || [], cur.activeSub);
    // Prefetch subtitle segera secara paralel sebelum video selesai buffering
    if(cur.activeSub){
      prefetchSubtitleTrack(cur.activeSub, r.data.referer);
    }
    var isEmbed = !!(r.data.is_embed || r.data.is_movie || (r.data.master && r.data.master.indexOf("http") === 0 && r.data.master.indexOf(".m3u8") < 0 && r.data.master.indexOf(".mp4") < 0 && r.data.master.indexOf("/api/player") < 0));
    var streamUrl = (r.data.master && (r.data.master.indexOf(".m3u8") >= 0 || r.data.master.indexOf("/hls") >= 0)) ? r.data.master : (picked ? picked.url : "");
    playUrl(streamUrl,r.data.referer,cur.activeSub,r.data.referer,resumeTime,isEmbed);
    window.Tatap.saveHist({slug:cur.slug,title:cur.title,episode:ep,mode:cur.mode}).then(function(){renderContinue();});
  }).catch(function(err){
    $("pm-spinner").classList.add("hidden");
    $("pm-status").textContent="KONEKSI GAGAL: "+(err&&err.message||err);
    toast("Koneksi gagal saat resolve: "+(err&&err.message||err));
  });
}
function renderVariants(){
  var box=$("pm-variants");if(box)box.innerHTML="";
  var sel=$("pm-quality-select");if(sel)sel.innerHTML="";
  var vs=(cur.res&&cur.res.hlsLevels&&cur.res.hlsLevels.length)?cur.res.hlsLevels:((cur.res&&cur.res.variants)||[]);
  var activeQ=(cur.res&&cur.res.picked&&cur.res.picked.q)||(vs[0]&&vs[0].q)||"";
  if(window._hls && cur.res && cur.res.hlsLevels && cur.res.hlsLevels.length){
    if(window._hls.autoLevelEnabled || window._hls.currentLevel === -1){
      activeQ = "Auto";
    }
  }

  for(var i=0;i<vs.length;i++){
    (function(v){
      if(box){
        var b=document.createElement("button");
        b.textContent=v.q;
        if(v.q.toLowerCase()===activeQ.toLowerCase())b.className="active";
        b.addEventListener("click",function(){switchQ(v.q);});
        box.appendChild(b);
      }
      if(sel){
        var opt=document.createElement("option");
        opt.value=v.q;
        opt.textContent=v.q.toUpperCase();
        if(v.q.toLowerCase()===activeQ.toLowerCase())opt.selected=true;
        sel.appendChild(opt);
      }
    })(vs[i]);
  }
  if(sel){
    if(vs.length<=1){
      sel.classList.add("hidden");
    } else {
      sel.classList.remove("hidden");
    }
  }
}


// ==== Multi-subtitle dropdown ====

function pickSubtitleUrl(subtitles, preferLang){
  // Pilih URL track subtitle yang cocok. Prioritas:
  //   1) Track dengan label == preferLang (case-insensitive).
  //   2) Track dengan lang code == preferLang (misal "English" → "en").
  //   3) Track AI Indonesian kalau user prefer Indonesian / translate aktif + ada track English.
  //   4) Track dengan default: true.
  //   5) Track English (hindari Arabic alfabetik pertama).
  //   6) Track pertama kalau tidak ada yang match.
  // Return null kalau subtitles kosong (UI akan sembunyikan dropdown).
  if(!subtitles||!subtitles.length)return null;
  if(preferLang){
    var low=String(preferLang).toLowerCase();
    for(var i=0;i<subtitles.length;i++){
      var s=subtitles[i];
      if((s.label||"").toLowerCase()===low)return s.url;
    }
    // Partial match di label (misal "Indonesian" cocok "Indonesian (Bahasa)").
    for(var j=0;j<subtitles.length;j++){
      if(((subtitles[j].label)||"").toLowerCase().indexOf(low)===0)return subtitles[j].url;
    }
    // Match kode bahasa (English → en/id/ja).
    var langMap={"english":"en","indonesian":"id","japanese":"ja","spanish":"es","portuguese":"pt",
                 "french":"fr","german":"de","italian":"it","korean":"ko","chinese":"zh","arabic":"ar",
                 "russian":"ru","thai":"th","vietnamese":"vi","turkish":"tr","hindi":"hi"};
    var code=langMap[low];
    if(code){
      for(var k=0;k<subtitles.length;k++){
        if((subtitles[k].lang||"").toLowerCase()===code)return subtitles[k].url;
      }
    }
    // Kalau prefer Indonesian / translate on dan tidak ada track ID asli:
    // auto-pilih track GTX+, AI Fansub, atau Pure GTX translate dari track English.
    if((low==="indonesian"||low==="id"||low==="indonesian (gtx+)"||low==="indonesian (aigtx)"||low==="indonesian (ai)"||low==="indonesian (gtx)"||cur.translate)){
      var enTrack=null;
      for(var e=0;e<subtitles.length;e++){
        var elab=(subtitles[e].label||"").toLowerCase();
        var elang=(subtitles[e].lang||"").toLowerCase();
        if(elang==="en"||elab.indexOf("english")===0||elab==="en"){
          enTrack=subtitles[e];break;
        }
      }
      if(enTrack&&enTrack.url){
        if(low==="indonesian (gtx+)"||low==="indonesian (aigtx)") return "gtx+:"+enTrack.url;
        if(low==="indonesian (ai)") return "ai:"+enTrack.url;
        return "gtx:"+enTrack.url;
      }
    }
  }
  // Prioritaskan English jika ada
  for(var n=0;n<subtitles.length;n++){
    var nlab=(subtitles[n].label||"").toLowerCase();
    var nlang=(subtitles[n].lang||"").toLowerCase();
    if(nlang==="en"||nlab.indexOf("english")===0||nlab.indexOf("eng")===0)return subtitles[n].url;
  }
  // Fallback: default:true (selama bukan Arabic)
  for(var m=0;m<subtitles.length;m++){
    var mlab=(subtitles[m].label||"").toLowerCase();
    var mlang=(subtitles[m].lang||"").toLowerCase();
    if(subtitles[m].default && mlang!=="ar" && mlab.indexOf("arab")===-1)return subtitles[m].url;
  }
  // Fallback: track pertama yang bukan Arabic
  for(var p=0;p<subtitles.length;p++){
    var plab=(subtitles[p].label||"").toLowerCase();
    var plang=(subtitles[p].lang||"").toLowerCase();
    if(plang!=="ar"&&plab.indexOf("arab")===-1)return subtitles[p].url;
  }
  return subtitles[0].url;
}

function renderSubtitles(subtitles, activeUrl){
  var wrap=$("pm-subs-wrap");
  var sel=$("pm-subs");
  if(!wrap||!sel)return;
  // Dropdown hanya tampil kalau ada minimal 1 track subtitle.
  // Kalau 0 → sembunyikan wrap (UI tetap clean).
  if(!subtitles||!subtitles.length){
    wrap.classList.add("hidden");
    sel.innerHTML="";
    return;
  }
  wrap.classList.remove("hidden");
  sel.innerHTML="";
  // Opsi pertama: "Off" (matikan subtitle).
  var offOpt=document.createElement("option");
  offOpt.value="";
  offOpt.textContent="Off";
  sel.appendChild(offOpt);
  // Tambah opsi "Indonesian (AI)", "Indonesian (GTX+)", dan "Indonesian (Google GTX)" kalau ada track English.
  var englishTrack=null;
  for(var i=0;i<subtitles.length;i++){
    (function(s){
      var o=document.createElement("option");
      o.value=s.url||"";
      o.textContent=s.label||("Subtitle "+(i+1));
      if(s.default)o.textContent+=" (Default)";
      if(activeUrl&&s.url===activeUrl)o.selected=true;
      sel.appendChild(o);
      // deteksi track English untuk AI-translate source
      if(!englishTrack){
        var lab=(s.label||"").toLowerCase();
        var lcode=(s.lang||"").toLowerCase();
        if(lcode==="en"||lab.indexOf("english")===0||lab==="en"){
          englishTrack=s;
        }
      }
    })(subtitles[i]);
  }
  if(englishTrack&&englishTrack.url){
    var gtxOpt=document.createElement("option");
    gtxOpt.value="gtx:"+englishTrack.url;
    gtxOpt.textContent="Indonesian (Google GTX)";
    gtxOpt.setAttribute("data-gtx-source",englishTrack.url);
    if(activeUrl&&(activeUrl===gtxOpt.value||(activeUrl.indexOf("gtx:")===0&&activeUrl.slice(4)===englishTrack.url))){
      gtxOpt.selected=true;
    }
    sel.appendChild(gtxOpt);

    var gtxplusOpt=document.createElement("option");
    gtxplusOpt.value="gtx+:"+englishTrack.url;
    gtxplusOpt.textContent="Indonesian (GTX+)";
    gtxplusOpt.setAttribute("data-gtxplus-source",englishTrack.url);
    if(activeUrl&&(activeUrl===gtxplusOpt.value||(activeUrl.indexOf("gtx+:")===0&&activeUrl.slice(5)===englishTrack.url)||(activeUrl.indexOf("aigtx:")===0&&activeUrl.slice(6)===englishTrack.url))){
      gtxplusOpt.selected=true;
    }
    sel.appendChild(gtxplusOpt);

    var aiOpt=document.createElement("option");
    aiOpt.value="ai:"+englishTrack.url;
    aiOpt.textContent="Indonesian (AI Fansub)";
    aiOpt.setAttribute("data-ai-source",englishTrack.url);
    if(activeUrl&&(activeUrl===aiOpt.value||(activeUrl.indexOf("ai:")===0&&activeUrl.slice(3)===englishTrack.url))){
      aiOpt.selected=true;
    }
    sel.appendChild(aiOpt);
  }
  // Set value juga kalau match dari default tidak ketemu (URL di pickSubtitleUrl).
  if(activeUrl){
    sel.value=activeUrl;
  }else{
    sel.value="";  // Off
  }
  // Event listener: ganti track aktif seketika + simpan preferensi.
  sel.onchange=function(){
    var url=sel.value;
    cur.activeSub=url||null;
    // Track GTX+: synthetic URL "gtx+:<url>" (atau legacy "aigtx:<url>").
    if(url&&(url.indexOf("gtx+:")===0||url.indexOf("aigtx:")===0)){
      cur.translate=false;
      switchSubtitleTrack(url,"id");
      cur.subLang="Indonesian (GTX+)";
      window.Tatap.setSetting({sub_lang:"Indonesian (GTX+)"}).then(function(){}).catch(function(){});
      return;
    }
    // Track AI Fansub: synthetic URL "ai:<url>". Extract realUrl + panggil translate.
    if(url&&url.indexOf("ai:")===0){
      cur.translate=true;
      try{localStorage.setItem("tatap_translate","1");}catch(e){}
      syncTranslate();
      switchSubtitleTrack(url,"id");
      cur.subLang="Indonesian (AI)";
      window.Tatap.setSetting({sub_lang:"Indonesian (AI)"}).then(function(){}).catch(function(){});
      return;
    }
    // Track Google GTX: synthetic URL "gtx:<url>".
    if(url&&url.indexOf("gtx:")===0){
      cur.translate=false;
      switchSubtitleTrack(url,"id");
      cur.subLang="Indonesian (GTX)";
      window.Tatap.setSetting({sub_lang:"Indonesian (GTX)"}).then(function(){}).catch(function(){});
      return;
    }
    // Update <track> live tanpa pause/reload video.
    switchSubtitleTrack(url);
    // Cari label untuk disimpan ke settings (server-side preference).
    var label="";
    if(url){
      for(var j=0;j<subtitles.length;j++){
        if(subtitles[j].url===url){label=subtitles[j].label||"";break;}
      }
    }
    if(label){
      cur.subLang=label;
      window.Tatap.setSetting({sub_lang:label}).then(function(){}).catch(function(){});
      toast("Subtitle: "+label);
    }else{
      cur.subLang="";
      window.Tatap.setSetting({sub_lang:""}).then(function(){}).catch(function(){});
      toast("Subtitle: Off");
    }
  };
}

function vttTime(s){
  var m=/^(?:(\d+):)?([0-5]?\d):([0-5]\d)(?:[.,](\d{1,3}))?$/.exec((s||"").trim());
  if(!m)return -1;
  var ms=m[4]?parseInt((m[4]+"000").slice(0,3),10):0;
  return (m[1]?parseInt(m[1],10)*3600:0)+parseInt(m[2],10)*60+parseInt(m[3],10)+ms/1000;
}
function parseVtt(text){
  var out=[];
  var lines=String(text||"").replace(/\r\n?/g,"\n").split("\n");
  var i=0;
  if(lines[0]&&lines[0].indexOf("WEBVTT")===0)i=1;
  var start=-1,end=-1,buf=[];
  var flush=function(){
    if(start>=0&&end>start&&buf.length){
      var plain=buf.map(function(x){return x.replace(/<[^>]+>/g,"");}).join("\n");
      var html=buf.map(function(x){return esc(x);}).join("<br>");
      html=html.replace(/&lt;[^&]*?&gt;/g,"");
      out.push({start:start,end:end,html:html,plain:plain});
    }
    start=-1;end=-1;buf=[];
  };
  for(;i<lines.length;i++){
    var ln=lines[i].trim();
    if(!ln){flush();continue;}
    if(ln.indexOf("-->")>=0){
      flush();
      var p=ln.split("-->");
      start=vttTime(p[0]);end=vttTime((p[1]||"").trim().split(" ")[0]);
      continue;
    }
    if(/^(NOTE|STYLE|REGION)/.test(ln))continue;
    if(start>=0)buf.push(ln);
  }
  flush();
  return out;
}
function clearOverlay(){
  var box=$("pm-subs-overlay");
  if(!box)return;
  var s=box.querySelector("span");
  if(s){s.innerHTML="";s._last="";}
}
function isVideoFullscreen(){
  var v=$("vid");
  if(!v)return false;
  var fsEl=document.fullscreenElement||document.webkitFullscreenElement||document.mozFullScreenElement||document.msFullscreenElement;
  if(fsEl&&fsEl===v)return true;
  if(v.webkitDisplayingFullscreen)return true;
  return false;
}
function isFullscreenActive(){
  var v=$("vid");
  var fsEl=document.fullscreenElement||document.webkitFullscreenElement||document.mozFullScreenElement||document.msFullscreenElement;
  if(fsEl)return true;
  if(v&&v.webkitDisplayingFullscreen)return true;
  return false;
}
function syncFullscreenSubtitles(){
  var v=$("vid");
  if(!v||!v.textTracks)return;
  var isVidFs=isVideoFullscreen();
  for(var i=0;i<v.textTracks.length;i++){
    var t=v.textTracks[i];
    if(t.label&&t.label.indexOf("Tatap")>=0){
      t.mode=isVidFs?"showing":"hidden";
    }
  }
  paintCue();
}
function syncNativeTextTrack(vttText, cues, langCode){
  var v=$("vid");
  if(!v)return;

  var oldTracks=v.querySelectorAll("track.tatap-sub-track");
  for(var i=0;i<oldTracks.length;i++){
    var trk=oldTracks[i];
    if(trk.src&&trk.src.indexOf("blob:")===0){
      try{URL.revokeObjectURL(trk.src);}catch(e){}
    }
    if(trk.parentNode)trk.parentNode.removeChild(trk);
  }

  if(v.textTracks){
    for(var j=0;j<v.textTracks.length;j++){
      if(v.textTracks[j].label&&v.textTracks[j].label.indexOf("Tatap")>=0){
        v.textTracks[j].mode="disabled";
      }
    }
  }

  if(!vttText&&(!cues||!cues.length))return;

  try{
    var trackEl=document.createElement("track");
    trackEl.className="tatap-sub-track";
    trackEl.kind="subtitles";
    trackEl.label="Tatap Subtitle";
    trackEl.srclang=langCode||"id";
    trackEl.default=true;

    if(vttText&&window.Blob&&window.URL&&window.URL.createObjectURL){
      var blob=new Blob([vttText],{type:"text/vtt"});
      trackEl.src=URL.createObjectURL(blob);
    }

    var applyMode=function(){
      if(trackEl.track){
        trackEl.track.mode=isVideoFullscreen()?"showing":"hidden";
      }
    };

    trackEl.addEventListener("load",applyMode);
    v.appendChild(trackEl);
    applyMode();

    setTimeout(function(){
      if(trackEl.track&&(!trackEl.track.cues||trackEl.track.cues.length===0)&&cues&&cues.length&&window.VTTCue){
        for(var k=0;k<cues.length;k++){
          var c=cues[k];
          var plain=c.plain||(c.html?c.html.replace(/<br\s*\/?>/gi,"\n").replace(/<[^>]+>/g,""):"");
          try{
            trackEl.track.addCue(new VTTCue(c.start,c.end,plain));
          }catch(e){}
        }
        applyMode();
      }
    },200);
  }catch(err){
    console.warn("syncNativeTextTrack error:",err);
  }
}
function toggleFullscreen(){
  var v=$("vid");
  var stage=document.querySelector(".ambient-stage");
  var fsEl=document.fullscreenElement||document.webkitFullscreenElement||document.mozFullScreenElement||document.msFullscreenElement;
  var isVideoFs=(v&&v.webkitDisplayingFullscreen);

  if(fsEl||isVideoFs){
    if(document.exitFullscreen){
      try{document.exitFullscreen().catch(function(){});}catch(e){}
    }else if(document.webkitExitFullscreen){
      try{document.webkitExitFullscreen();}catch(e){}
    }else if(document.mozCancelFullScreen){
      try{document.mozCancelFullScreen();}catch(e){}
    }else if(document.msExitFullscreen){
      try{document.msExitFullscreen();}catch(e){}
    }
    if(v&&v.webkitExitFullscreen&&v.webkitDisplayingFullscreen){
      try{v.webkitExitFullscreen();}catch(e){}
    }
    return;
  }

  // iOS Safari video native fullscreen
  if(v&&v.webkitEnterFullscreen&&(!stage||!stage.requestFullscreen)){
    try{
      v.webkitEnterFullscreen();
      return;
    }catch(err){
      console.warn("webkitEnterFullscreen error:",err);
    }
  }

  var enterVideoFs=function(){
    if(!v)return;
    if(v.requestFullscreen){
      try{v.requestFullscreen().catch(function(){if(v.webkitEnterFullscreen)v.webkitEnterFullscreen();});}catch(e){if(v.webkitEnterFullscreen)v.webkitEnterFullscreen();}
    }else if(v.webkitRequestFullscreen){
      try{v.webkitRequestFullscreen();}catch(e){if(v.webkitEnterFullscreen)v.webkitEnterFullscreen();}
    }else if(v.mozRequestFullScreen){
      try{v.mozRequestFullScreen();}catch(e){}
    }else if(v.msRequestFullscreen){
      try{v.msRequestFullscreen();}catch(e){}
    }else if(v.webkitEnterFullscreen){
      try{v.webkitEnterFullscreen();}catch(e){}
    }
  };

  if(stage&&(stage.requestFullscreen||stage.webkitRequestFullscreen||stage.mozRequestFullScreen||stage.msRequestFullscreen)){
    var p;
    try{
      if(stage.requestFullscreen){
        p=stage.requestFullscreen();
      }else if(stage.webkitRequestFullscreen){
        p=stage.webkitRequestFullscreen();
      }else if(stage.mozRequestFullScreen){
        p=stage.mozRequestFullScreen();
      }else if(stage.msRequestFullscreen){
        p=stage.msRequestFullscreen();
      }
      if(p&&p.catch){
        p.catch(function(err){
          console.warn("stage.requestFullscreen rejected, falling back to video:",err);
          enterVideoFs();
        });
      }
    }catch(err){
      console.warn("stage fullscreen exception, falling back to video:",err);
      enterVideoFs();
    }
  }else{
    enterVideoFs();
  }
}
function paintCue(){
  var box=$("pm-subs-overlay");
  var v=$("vid");
  if(!box||!v)return;
  var s=box.querySelector("span");
  if(!s)return;
  if($("player-modal").classList.contains("hidden")){s.innerHTML="";return;}
  var t=v.currentTime||0;
  var html="";
  for(var i=0;i<cur.cues.length;i++){
    if(t>=cur.cues[i].start&&t<=cur.cues[i].end){html=cur.cues[i].html;break;}
  }
  if(s._last!==html){s.innerHTML=html;s._last=html;}
}
function prefetchSubtitleTrack(url, ref, langCode){
  if(!url)return null;
  var targetUrl = url;
  var targetLang = langCode || "";
  var mode = "";
  if(targetUrl.indexOf("gtx+:")===0){
    targetUrl = targetUrl.slice(5);
    if(!targetLang) targetLang = "id";
    mode = "gtx+";
  }else if(targetUrl.indexOf("aigtx:")===0){
    targetUrl = targetUrl.slice(6);
    if(!targetLang) targetLang = "id";
    mode = "gtx+";
  }else if(targetUrl.indexOf("ai:")===0){
    targetUrl = targetUrl.slice(3);
    if(!targetLang) targetLang = "id";
    mode = "ai";
  }else if(targetUrl.indexOf("gtx:")===0){
    targetUrl = targetUrl.slice(4);
    if(!targetLang) targetLang = "id";
    mode = "gtx";
  }
  var qs = "url=" + encodeURIComponent(targetUrl) + "&referer=" + encodeURIComponent(ref || "");
  if(targetLang) qs += "&lang=" + encodeURIComponent(targetLang);
  if(mode) qs += "&mode=" + encodeURIComponent(mode);
  var prox = "/api/player/sub?" + qs;

  // Cek apakah promise untuk URL yang sama sudah berjalan
  if(cur._subPrefetch && cur._subPrefetch.prox === prox){
    return cur._subPrefetch.promise;
  }

  var p = fetch(prox).then(function(r){
    if(!r.ok)throw new Error("HTTP "+r.status);
    var tier=r.headers.get("X-Translate-Tier")||"";
    var trErr=r.headers.get("X-Translate-Error")||"";
    var trModel=r.headers.get("X-Translate-Model")||"";
    var trMixed=r.headers.get("X-Translate-Mixed")||"";
    var trBg=r.headers.get("X-Translate-Background")||"";
    return r.text().then(function(t){
      return {text:t, tier:tier, error:trErr, model:trModel, mixed:trMixed, bg:trBg};
    });
  });

  cur._subPrefetch = {prox: prox, promise: p};
  return p;
}

function switchSubtitleTrack(url, langCode){
  // Render subtitle milik app (overlay div), bukan <track> native.
  // Style tidak lagi mengikuti setting caption Windows.
  // langCode opsional ("id", "ja", dst.) — backend akan translate kalau beda.
  var v=$("vid");
  if(!v)return;
  // Bersihkan track lama lalu kosongkan overlay.
  syncNativeTextTrack("", [], "");
  cur.cues=[];
  clearOverlay();
  if(cur._subUpgradeTimer){
    clearTimeout(cur._subUpgradeTimer);
    cur._subUpgradeTimer = null;
  }
  if(!url)return;
  var originalUrl = url;
  var trackMode = "none";
  if(url.indexOf("gtx+:")===0){
    url=url.slice(5);
    if(!langCode) langCode="id";
    trackMode = "gtx+";
  }else if(url.indexOf("aigtx:")===0){
    url=url.slice(6);
    if(!langCode) langCode="id";
    trackMode = "gtx+";
  }else if(url.indexOf("ai:")===0){
    url=url.slice(3);
    if(!langCode) langCode="id";
    trackMode = "ai";
  }else if(url.indexOf("gtx:")===0){
    url=url.slice(4);
    if(!langCode) langCode="id";
    trackMode = "gtx";
  }
  if(langCode==="id"){
    var waitMsg = "Menerjemahkan subtitle AI ke bahasa Indonesia...";
    if(trackMode==="gtx+"||trackMode==="aigtx") waitMsg = "Menerjemahkan subtitle GTX+ (Smart Fansub & Scene Detection)...";
    else if(trackMode==="gtx") waitMsg = "Menerjemahkan subtitle Google GTX...";
    toast(waitMsg, 3000);
    var obox=$("pm-subs-overlay");
    if(obox){
      var osp=obox.querySelector("span");
      if(osp){
        osp.textContent="[" + waitMsg + "]";
        osp._last=osp.textContent;
      }
    }
  }
  var ref=cur.res&&cur.res.referer||"";
  var subPromise = prefetchSubtitleTrack(originalUrl, ref, langCode);
  subPromise.then(function(res){
    clearOverlay();
    cur.cues=parseVtt(res.text);
    paintCue();
    syncNativeTextTrack(res.text, cur.cues, langCode);
    if(langCode==="id"){
      if(res.tier==="source"||res.tier==="source-fallback"){
        var msg="Gagal translate";
        if(res.error) msg+=": "+res.error;
        else msg+=" (menampilkan subtitle asli)";
        toast(msg, 6000);
      }else{
        var tierLabel = "AI Fansub" + (res.model ? " · "+res.model : "");
        if(res.tier === "gtx+" || res.tier === "cached-gtx+" || res.tier === "aigtx" || res.tier === "cached-aigtx"){
          tierLabel = (res.tier === "cached-gtx+" || res.tier === "cached-aigtx") ? "GTX+, tersimpan" : "GTX+ Translate";
        }else if(res.tier === "tier2"){
          tierLabel = trackMode === "gtx" ? "Google GTX" : "GTX+ (Instan)";
        }else if(res.tier === "cached-mt" || res.tier === "cached-gtx"){
          tierLabel = trackMode === "gtx" ? "Google GTX, tersimpan" : "GTX+, tersimpan";
        }else if(res.tier === "tier3"){
          tierLabel = "MyMemory — kaku";
        }else if(res.tier === "cached"){
          tierLabel = "AI Fansub, tersimpan";
        }
        var extra = "";
        if(res.mixed) extra = " · "+res.mixed+" baris via GTX";
        toast("Subtitle Indonesia siap ("+tierLabel+")! ("+cur.cues.length+" baris"+extra+")", 4000);

        // Jika mode AI Fansub dan disajikan instan via GTX+ / MT, upgrade di background saat AI selesai:
        if(trackMode === "ai" && (res.bg === "llm-translating" || res.tier === "tier2" || res.tier === "gtx+" || res.tier === "cached-gtx+" || res.tier === "aigtx" || res.tier === "cached-aigtx" || res.tier === "cached-mt")){
          var checkUpgrade = function(attempt){
            if(attempt > 20) return; // Maksimal ~5 menit
            cur._subUpgradeTimer = setTimeout(function(){
              var qs = "url=" + encodeURIComponent(url) + "&referer=" + encodeURIComponent(ref || "") + "&lang=id";
              fetch("/api/player/sub?" + qs).then(function(ur){
                var uTier = ur.headers.get("X-Translate-Tier") || "";
                var uModel = ur.headers.get("X-Translate-Model") || "";
                if(uTier === "cached" || uTier === "tier1"){
                  ur.text().then(function(uText){
                    cur.cues = parseVtt(uText);
                    paintCue();
                    syncNativeTextTrack(uText, cur.cues, "id");
                    var lbl = "AI Fansub" + (uModel ? " · " + uModel : "");
                    toast("✨ Subtitle berhasil di-upgrade ke " + lbl + "!", 5000);
                  });
                }else{
                  checkUpgrade(attempt + 1);
                }
              }).catch(function(){});
            }, 15000);
          };
          checkUpgrade(1);
        }
      }
    }
  }).catch(function(err){
    cur.cues=[];
    clearOverlay();
    syncNativeTextTrack("", [], "");
    if(langCode==="id"){
      toast("Gagal menerjemahkan subtitle: "+(err&&err.message||err));
    }
  });
}

var TouchGestures = {
  startX: 0,
  startY: 0,
  lastTap: 0,
  lastTapX: 0,
  mode: null,       // 'volume' | 'brightness' | 'seek' | null
  initVol: 1,
  initBright: 100,
  initTime: 0,
  currentBright: 100,
  osdTimer: null,
  armed: false,

  showOSD: function(icon, pct, text){
    var el = $("pm-gesture-osd");
    if(!el) return;
    $("pm-osd-icon").textContent = icon;
    $("pm-osd-bar").style.width = Math.max(0, Math.min(100, pct)) + "%";
    $("pm-osd-val").textContent = text != null ? text : Math.round(pct) + "%";
    el.classList.remove("hidden");
    clearTimeout(this.osdTimer);
    this.osdTimer = setTimeout(function(){ el.classList.add("hidden"); }, 1200);
  },

  triggerRipple: function(side, text){
    var rip = $(side === "left" ? "pm-ripple-left" : "pm-ripple-right");
    if(!rip) return;
    if(text) {
      var t = rip.querySelector(".ripple-text");
      if(t) t.textContent = text;
    }
    rip.classList.remove("active");
    void rip.offsetWidth; // force reflow
    rip.classList.add("active");
    setTimeout(function(){ rip.classList.remove("active"); }, 400);
    // Haptic feedback via native bridge or Web Vibration API
    if(window.TatapNative && window.TatapNative.vibrate){
      window.TatapNative.vibrate(25);
    } else if(navigator.vibrate){
      try{ navigator.vibrate(25); }catch(e){}
    }
  },

  bind: function(){
    if(this.armed) return;
    this.armed = true;
    var stage = document.querySelector(".ambient-stage");
    var v = $("vid");
    if(!stage || !v) return;

    var self = this;

    stage.addEventListener("touchstart", function(e){
      if(e.touches.length !== 1) return;
      var touch = e.touches[0];
      var rect = stage.getBoundingClientRect();
      self.startX = touch.clientX;
      self.startY = touch.clientY;
      self.mode = null;
      self.initVol = v.volume;
      self.initBright = self.currentBright;
      self.initTime = v.currentTime;
    }, {passive: true});

    stage.addEventListener("touchmove", function(e){
      if(e.touches.length !== 1) return;
      var touch = e.touches[0];
      var rect = stage.getBoundingClientRect();
      var dx = touch.clientX - self.startX;
      var dy = touch.clientY - self.startY;
      var relX = (self.startX - rect.left) / rect.width;

      if(!self.mode){
        if(Math.abs(dx) > 18 && Math.abs(dx) > Math.abs(dy)){
          self.mode = "seek";
        } else if(Math.abs(dy) > 18 && Math.abs(dy) > Math.abs(dx)){
          self.mode = (relX < 0.5) ? "brightness" : "volume";
        }
      }

      if(self.mode === "seek"){
        var dur = v.duration || 1400;
        var scrub = (dx / rect.width) * 90; // geser penuh layar = +/- 90 detik
        var target = Math.max(0, Math.min(dur, self.initTime + scrub));
        var diff = Math.round(target - self.initTime);
        var sign = diff >= 0 ? "+" : "";
        var min = Math.floor(target / 60);
        var sec = Math.floor(target % 60);
        var timeStr = min + ":" + (sec < 10 ? "0" : "") + sec;
        self.showOSD("⏩", (target / dur) * 100, timeStr + " (" + sign + diff + "s)");
        self._targetSeek = target;
      } else if(self.mode === "volume"){
        var deltaV = (-dy / rect.height) * 1.5;
        var nv = Math.max(0, Math.min(1, self.initVol + deltaV));
        v.volume = nv;
        v.muted = (nv === 0);
        var ic = nv === 0 ? "🔇" : (nv < 0.5 ? "🔉" : "🔊");
        self.showOSD(ic, nv * 100);
      } else if(self.mode === "brightness"){
        var deltaB = (-dy / rect.height) * 120;
        var nb = Math.max(20, Math.min(150, self.initBright + deltaB));
        self.currentBright = nb;
        v.style.filter = "brightness(" + (nb / 100) + ")";
        if(window.TatapNative && window.TatapNative.setBrightness){
          window.TatapNative.setBrightness(nb / 100);
        }
        self.showOSD("☀️", (nb / 150) * 100, Math.round(nb) + "%");
      }
    }, {passive: true});

    stage.addEventListener("touchend", function(e){
      if(self.mode === "seek" && self._targetSeek != null){
        v.currentTime = self._targetSeek;
        self._targetSeek = null;
        self.mode = null;
        return;
      }
      if(self.mode){
        self.mode = null;
        return;
      }

      // Deteksi tap & double-tap
      var now = Date.now();
      var rect = stage.getBoundingClientRect();
      var relX = (self.startX - rect.left) / rect.width;

      if(now - self.lastTap < 320 && Math.abs(self.startX - self.lastTapX) < 80){
        // Double Tap
        self.lastTap = 0; // reset
        if(relX < 0.35){
          v.currentTime = Math.max(0, v.currentTime - 10);
          self.triggerRipple("left", "-10s");
        } else if(relX > 0.65){
          v.currentTime = Math.min(v.duration || 99999, v.currentTime + 10);
          self.triggerRipple("right", "+10s");
        } else {
          if(v.paused) v.play(); else v.pause();
        }
      } else {
        self.lastTap = now;
        self.lastTapX = self.startX;
      }
    }, {passive: true});
  }
};

function armAutohide(){
  var stage=document.querySelector(".ambient-stage");
  var shell=document.querySelector(".player-shell");
  TouchGestures.bind();
  if(!stage||stage._armed)return;
  stage._armed=true;
  var v=$("vid");
  var t=null;
  var show=function(){
    stage.classList.remove("idle");
    if(shell)shell.classList.remove("idle");
    clearTimeout(t);
    t=setTimeout(function(){
      if(v.paused)return;
      v.removeAttribute("controls");
      stage.classList.add("idle");
      if(shell)shell.classList.add("idle");
    },2800);
  };
  var wake=function(){
    if(!v.hasAttribute("controls"))v.setAttribute("controls","");
    show();
  };
  ["mousemove","touchstart","click"].forEach(function(ev){stage.addEventListener(ev,wake,{passive:true});});
  v.addEventListener("play",show);
  v.addEventListener("pause",function(){clearTimeout(t);v.setAttribute("controls","");stage.classList.remove("idle");if(shell)shell.classList.remove("idle");});
  v.addEventListener("seeking",show);
  show();
}
function playUrl(url,referrer,sub,subRef,resumeTime,isEmbed){
  var v=$("vid");
  var embed=$("pm-embed");
  if(isEmbed){
    if(v){
      try{v.pause();v.removeAttribute("src");v.load();}catch(e){}
      v.classList.add("hidden");
    }
    if(window._hls){try{window._hls.destroy();window._hls=null;}catch(e){}}
    if(embed){
      embed.classList.remove("hidden");
      embed.src=url;
      embed.onload=function(){
        $("pm-spinner").classList.add("hidden");
      };
    }
    $("pm-spinner").classList.remove("hidden");
    $("pm-status").textContent="memuat pemutar film (anti-ads)...";
    $("pm-subs-wrap").classList.add("hidden");
    armAutohide();
    return;
  }

  if(embed){
    embed.src="about:blank";
    embed.classList.add("hidden");
  }
  if(v){
    v.classList.remove("hidden");
    v.muted=false;
    if(v.volume===0) v.volume=1.0;
  }
  $("pm-subs-wrap").classList.remove("hidden");
  var b = (typeof apiBase === "function") ? apiBase() : "";
  var prox=b+"/api/player/video?url="+encodeURIComponent(url)+"&referer="+encodeURIComponent(referrer||"");
  try{
    var m=/^(.*\/)index-(f\d+-v\d+-a\d+)\.m3u8/.exec(url);
    if(m){
      for(var wi=1;wi<=2;wi++){
        (function(n){
          var seg=m[1]+"seg-"+n+"-"+m[2]+".jpg";
          fetch("/api/player/video?url="+encodeURIComponent(seg)+"&referer="+encodeURIComponent(referrer||""),{mode:"no-cors"}).catch(function(){});
        })(wi);
      }
    }
  }catch(e){}
  // Bersihkan <track> lama lalu pasang track subtitle aktif (live switch).
  // Fungsi switchSubtitleTrack() menhandle Off (hapus semua) dan replace.
  switchSubtitleTrack(sub || null);
  $("pm-spinner").classList.remove("hidden");
  $("pm-status").textContent="buffering...";
  var onCan=function(){
    $("pm-spinner").classList.add("hidden");
    if(resumeTime && resumeTime > 0){
      try{v.currentTime = resumeTime;}catch(e){}
    }
  };
  v.addEventListener("canplay",onCan,{once:true});
  var cleanPath = (url || "").split("?")[0].toLowerCase();
  var isSeg = cleanPath.endsWith(".ts") || cleanPath.endsWith(".ts.jpg") || cleanPath.endsWith(".mp4") || cleanPath.endsWith(".aac");
  var isHls = !isSeg && ((url.indexOf(".m3u8") >= 0) || (url.indexOf("format=m3u8") >= 0) || (url.indexOf("/api/hls") >= 0) || (url.indexOf("/hls/playlist") >= 0));
  if(window.Hls&&window.Hls.isSupported()&&isHls){
    if(window._hls){try{window._hls.destroy();}catch(e){}}
    var h=new Hls({
      maxBufferLength:30,
      maxMaxBufferLength:60,
      maxBufferSize:40*1000*1000,
      startLevel:-1,
      capLevelToPlayerSize:true,
      fragLoadingMaxRetry:6,
      manifestLoadingMaxRetry:4,
      levelLoadingMaxRetry:4,
      fragLoadingMaxRetryTimeout:12000,
      backBufferLength:30,
      liveSyncDurationCount:2,
      maxFragLookUpTolerance:0.5,
      testBandwidth:false,
      progressive:true,
      lowLatencyMode:false,
      defaultAudioCodec:"mp4a.40.2",
      enableWorker:true
    });
    window._hls=h;
    h.on(Hls.Events.AUDIO_TRACKS_UPDATED,function(ev,data){
      if(data&&data.audioTracks&&data.audioTracks.length){
        var isDub = (cur.mode === "dub");
        var selectedIdx = -1;
        if(isDub){
          for(var ai=0;ai<data.audioTracks.length;ai++){
            var t = data.audioTracks[ai];
            var lang = (t.lang || "").toLowerCase();
            var name = (t.name || "").toLowerCase();
            if(lang === "en" || name.indexOf("english") >= 0 || name.indexOf("dub") >= 0){
              selectedIdx = ai;
              break;
            }
          }
        } else {
          for(var ai=0;ai<data.audioTracks.length;ai++){
            var t = data.audioTracks[ai];
            var lang = (t.lang || "").toLowerCase();
            var name = (t.name || "").toLowerCase();
            if(lang === "ja" || lang === "jpn" || name.indexOf("japan") >= 0 || t.default){
              selectedIdx = ai;
              break;
            }
          }
        }
        if(selectedIdx !== -1){
          h.audioTrack = selectedIdx;
        } else if(h.audioTrack === -1 || h.audioTrack === undefined){
          h.audioTrack = 0;
        }
      }
    });
    h.on(Hls.Events.FRAG_BUFFERED,function(){
      try{
        var nxt=null;
        if(h.levels&&h.levelDetails&&h.levelDetails.fragments){
          var fr=h.levelDetails.fragments;
          for(var fi=0;fi<fr.length;fi++){if(!fr[fi].loaded){nxt=fr[fi];break;}}
        }
        if(nxt&&nxt.url){
          fetch("/api/player/video?url="+encodeURIComponent(nxt.url)+"&referer="+encodeURIComponent(referrer||""),{mode:"no-cors",priority:"low"}).catch(function(){});
        }
      }catch(e){}
    });
    h.on(Hls.Events.MANIFEST_PARSED,function(ev,data){
      if(data&&data.levels&&data.levels.length>1){
        var hlsVars=[];
        for(var li=0;li<data.levels.length;li++){
          var lvl=data.levels[li];
          var lHeight = lvl.height || 0;
          var lLabel = lHeight ? (lHeight + "p") : ("Level " + (li+1));
          hlsVars.push({q: lLabel, levelIdx: li, height: lHeight, url: lvl.url || (lvl.details && lvl.details.url) || ""});
        }
        // Urutkan dari tertinggi ke terendah
        hlsVars.sort(function(a,b){return b.height - a.height;});
        // Tambahkan opsi Auto di awal
        hlsVars.unshift({q: "Auto", levelIdx: -1, height: 99999, url: ""});
        cur.res = cur.res || {};
        cur.res.hlsLevels = hlsVars;
        renderVariants();
        // Terapkan kualitas yang cocok jika user memilih kualitas tertentu
        if(cur.quality && cur.quality.toLowerCase() !== "auto" && cur.quality.toLowerCase() !== "best"){
          var targetQ = cur.quality.toLowerCase();
          for(var qk=0; qk<hlsVars.length; qk++){
            if(hlsVars[qk].q.toLowerCase().indexOf(targetQ) >= 0 || targetQ.indexOf(hlsVars[qk].q.toLowerCase()) >= 0){
              if(hlsVars[qk].levelIdx !== -1){
                h.currentLevel = hlsVars[qk].levelIdx;
                break;
              }
            }
          }
        }
      }
    });
    h.on(Hls.Events.LEVEL_SWITCHED,function(ev,data){
      if(cur.res && cur.res.hlsLevels){
        var curIdx = h.currentLevel;
        var autoMode = (h.autoLevelEnabled || curIdx === -1);
        var activeLabel = "AUTO";
        if(!autoMode){
          for(var hi=0;hi<cur.res.hlsLevels.length;hi++){
            if(cur.res.hlsLevels[hi].levelIdx === curIdx){
              activeLabel = cur.res.hlsLevels[hi].q.toUpperCase();
              break;
            }
          }
        }
        var sel=$("pm-quality-select");
        if(sel && !sel.classList.contains("user-interacting")){
          sel.value = autoMode ? "Auto" : activeLabel.toLowerCase();
        }
      }
    });
    h.loadSource(prox);
    h.attachMedia(v);
    h.on(Hls.Events.ERROR,function(ev,d){
      if(!d)return;
      if(d.fatal){
        if(d.type===Hls.ErrorTypes.NETWORK_ERROR){
          // Coba pulihkan koneksi network sekali sebelum menyerah
          if(!h._networkRetried){
            h._networkRetried=true;
            $("pm-status").textContent="mencoba memulihkan koneksi stream...";
            h.startLoad();
            return;
          }
        }else if(d.type===Hls.ErrorTypes.MEDIA_ERROR){
          if(!h._mediaRetried){
            h._mediaRetried=true;
            $("pm-status").textContent="mencoba memulihkan codec media...";
            h.recoverMediaError();
            return;
          }
        }
        $("pm-status").textContent="player error: "+(d.type||"fatal")+" — "+(d.details||"");
        try{h.destroy();}catch(_){}
        return;
      }
      // Non-fatal: fragLoadError / manifestLoadError / networkError — kalau host
      // mati (dramahot.top RST), proxy return 502; HLS.js fire ini. Beri pesan
      // jelas di spinner & stop setelah beberapa retry agar user tidak hang.
      var n=(h.config&&h.config.fragLoadingMaxRetry)||4;
      if(d.details==="fragLoadError"||d.details==="manifestLoadError"||d.details==="networkError"){
        $("pm-status").textContent="gagal load: "+(d.details||"network");
      }
    });
  }else{
    v.src=isHls?prox:url;
  }
  v.play().catch(function(err){
    $("pm-spinner").classList.add("hidden");
    if(err && err.name === "NotAllowedError"){
      v.muted = true;
      v.play().catch(function(){});
    }
  });
  armAutohide();
}
function switchQ(q){
  var qLow = String(q||"").toLowerCase();
  if(cur.res && (cur.res.is_embed || cur.res.is_movie || cur.res.source === "film") && cur.res.variants){
    for(var i=0;i<cur.res.variants.length;i++){
      if(cur.res.variants[i].q.toLowerCase()===qLow){
        var vTarget = cur.res.variants[i];
        cur.res.picked = vTarget;
        renderVariants();
        var isEmbedTarget = (vTarget.is_embed !== undefined) ? vTarget.is_embed : (vTarget.url.indexOf("http") === 0 && vTarget.url.indexOf(".m3u8") < 0);
        var ref = vTarget.referer || cur.res.referer;
        playUrl(vTarget.url, ref, cur.activeSub || cur.res.sub, ref, 0, isEmbedTarget);
        toast("Server: " + vTarget.q);
        return;
      }
    }
  }
  // 1. Jika HLS.js aktif dan memiliki live levels, ganti level secara instan tanpa reload!
  if(window._hls && cur.res && cur.res.hlsLevels && cur.res.hlsLevels.length){
    for(var hi=0;hi<cur.res.hlsLevels.length;hi++){
      var hl = cur.res.hlsLevels[hi];
      if(hl.q.toLowerCase() === qLow){
        if(hl.levelIdx === -1){
          window._hls.currentLevel = -1; // Auto adaptive mode
          toast("Resolusi: AUTO (Adaptif)");
        } else {
          window._hls.currentLevel = hl.levelIdx;
          toast("Resolusi: " + hl.q.toUpperCase());
        }
        if(cur.res.picked) cur.res.picked.q = hl.q;
        renderVariants();
        return;
      }
    }
  }

  // 2. Fallback: reload varian URL jika bukan live multi-level HLS.js
  if(!cur.res||!cur.res.variants)return;
  var curTime = ($("vid") && $("vid").currentTime) || 0;
  for(var i=0;i<cur.res.variants.length;i++){
    if(cur.res.variants[i].q.toLowerCase()===qLow){
      cur.res.picked=cur.res.variants[i];
      renderVariants();
      playUrl(cur.res.variants[i].url,cur.res.referer,cur.activeSub||cur.res.sub,cur.res.referer,curTime);
      toast("Resolusi: "+cur.res.variants[i].q.toUpperCase());
      return;
    }
  }
}

function updatePrevNext(){
  var idx=-1;
  for(var i=0;i<cur.eps.length;i++)if(cur.eps[i].ep===cur.ep)idx=i;
  $("pm-prev").disabled=idx<=0;
  $("pm-next").disabled=idx<0||idx>=cur.eps.length-1;
}
function stepEp(d){
  if($("player-modal").classList.contains("hidden"))return;
  var idx=-1;
  for(var i=0;i<cur.eps.length;i++)if(cur.eps[i].ep===cur.ep)idx=i;
  var nxt=cur.eps[idx+d];
  if(nxt)openPlayer(nxt.ep);
  else toast(d>0?"Sudah episode terakhir":"Sudah episode pertama");
}
function closePlayer(){
  var embed=$("pm-embed");
  if(embed){
    embed.src="about:blank";
    embed.classList.add("hidden");
  }
  var v=$("vid");
  if(v){
    v.classList.remove("hidden");
    try{v.pause();}catch(e){}
    v.removeAttribute("src");
    try{v.load();}catch(e){}
  }
  if(window._hls){try{window._hls.destroy();window._hls=null;}catch(e){}}
  cur.cues=[];
  clearOverlay();
  syncNativeTextTrack("", [], "");
  $("player-modal").classList.add("hidden");
  $("pm-spinner").classList.add("hidden");
}
function playMPV(){
  window.Tatap.playMPV({slug:cur.slug,title:cur.title,ep:cur.ep||1,mode:cur.mode,quality:cur.quality}).then(function(r){
    toast(r.success?("MPV: "+r.data.picked.q):("ERROR: "+r.error));
  });
}
function renderContinue(){
  window.Tatap.history().then(function(r){
    var h=(r.data||[]).slice(0,10);
    var sec=$("continue-sec");
    if(!h.length){sec.classList.add("hidden");return;}
    var inCari=!window.Tui||Tui.view()==="cari";
    sec.classList.toggle("hidden",!inCari);
    var box=$("continue-row");box.innerHTML="";
    for(var i=0;i<h.length;i++){
      (function(x){
        var d=document.createElement("div");d.className="hist-card";
        var b=document.createElement("b");b.textContent=x.title;d.appendChild(b);
        var s=document.createElement("span");
        s.innerHTML="<span style='color:var(--ok);font-size:9px;'>●</span> EP "+x.episode+" · "+(x.mode||"sub").toUpperCase()+" · Putar ▶";
        d.appendChild(s);
        d.addEventListener("click",function(){
          cur.slug=x.slug;cur.title=x.title;cur.mode=x.mode||"sub";syncSeg();
          openTitle(x.slug,x.title);openPlayer(x.episode);
        });
        box.appendChild(d);
      })(h[i]);
    }
  }).catch(function(){});
}
function setFallback(r,g,b){
  var fb=$("ambient-fallback");
  if(!fb)return;
  fb.style.background="radial-gradient(60% 90% at 50% 50%, rgb("+r+","+g+","+b+"), transparent 70%)";
}
function startAmbient(){
  var cv=$("ambient"),ctx=null;
  try{ctx=cv.getContext("2d",{willReadFrequently:true});}catch(e){ctx=cv.getContext("2d");}
  var v=$("vid");
  v.setAttribute("crossorigin","anonymous");
  var tmp=document.createElement("canvas");
  tmp.width=48;tmp.height=27;
  var tctx=null;
  try{tctx=tmp.getContext("2d",{willReadFrequently:true});}catch(e){tctx=tmp.getContext("2d");}
  setInterval(function(){
    if(document.body.classList.contains("no-ambient"))return;
    if($("player-modal").classList.contains("hidden"))return;
    if(v.paused||v.ended||v.readyState<2||v.videoWidth===0)return;
    try{
      tctx.drawImage(v,0,0,48,27);
      var px;
      try{px=tctx.getImageData(0,0,48,27).data;}
      catch(taint){
        var h=0,s=String(cur.slug)+cur.ep;
        for(var k=0;k<s.length;k++)h=(h*31+s.charCodeAt(k))%360;
        setFallback(Math.round(90+80*Math.abs(Math.sin(h))),120,220);
        return;
      }
      var r=0,g=0,b=0,n=0;
      for(var i=0;i<px.length;i+=12){r+=px[i];g+=px[i+1];b+=px[i+2];n++;}
      r=Math.round(r/n);g=Math.round(g/n);b=Math.round(b/n);
      var g2=ctx.createLinearGradient(0,0,96,54);
      g2.addColorStop(0,"rgb("+r+","+g+","+b+")");
      g2.addColorStop(1,"rgb("+Math.round(b*.7)+","+Math.round(r*.6)+","+Math.round(g*.8)+")");
      ctx.fillStyle=g2;
      ctx.fillRect(0,0,96,54);
      setFallback(r,g,b);
    }catch(e){}
  },500);
}
function onKeyPlayer(e){
  var t=(e.target.tagName||"");
  var typing=t==="INPUT"||t==="SELECT"||t==="TEXTAREA";
  if(typing&&e.key==="Escape"){e.target.blur();return;}
  var v=$("vid");
  if(e.key==="Escape"){
    var fsEl=document.fullscreenElement||document.webkitFullscreenElement||document.mozFullScreenElement||document.msFullscreenElement;
    if(fsEl){
      // Fullscreen will be closed natively by browser, keep player modal open
      return;
    }
    if($("drawer-panel") && !$("drawer-panel").classList.contains("hidden")){closeDrawer();return;}
    if($("update-modal") && !$("update-modal").classList.contains("hidden")){closeUpdateModal();return;}
    if(!$("player-modal").classList.contains("hidden"))closePlayer();
    else if(!$("title-modal").classList.contains("hidden"))closeTitle();
    return;
  }
  if($("player-modal").classList.contains("hidden"))return;
  if(e.key===" "){e.preventDefault();if(v.paused)v.play();else v.pause();}
  else if(e.key==="f"||e.key==="F"){e.preventDefault();toggleFullscreen();}
  else if(e.key==="n")stepEp(1);
  else if(e.key==="p")stepEp(-1);
  else if(e.key==="m")v.muted=!v.muted;
  else if(e.key==="s"||e.key==="S")switchSource();
  else if(e.key==="ArrowRight"){e.preventDefault();v.currentTime+=5;}
  else if(e.key==="ArrowLeft"){e.preventDefault();v.currentTime-=5;}
}

function syncSubSize(){
  var box=$("pm-subs-overlay");
  if(box){
    box.classList.remove("sz-s","sz-m","sz-l");
    box.classList.add("sz-"+(cur.subSize||"m"));
  }
  document.querySelectorAll(".sub-size button").forEach(function(b){
    b.classList.toggle("active",b.getAttribute("data-subsize")===(cur.subSize||"m"));
  });
}
function setSubSize(sz){
  if(sz!=="s"&&sz!=="m"&&sz!=="l")return;
  cur.subSize=sz;
  try{localStorage.setItem("tatap_subsize",sz);}catch(e){}
  syncSubSize();
}

function syncTranslate(){
  var btn=$("pm-translate");
  if(!btn)return;
  btn.setAttribute("data-on",cur.translate?"1":"0");
  btn.title="Translate ID: "+(cur.translate?"on":"off")+" (butuh track English sebagai source)";
}
function setTranslate(on){
  cur.translate=!!on;
  try{localStorage.setItem("tatap_translate",cur.translate?"1":"0");}catch(e){}
  syncTranslate();
  // Re-render dropdown agar opsi Indonesian (AI) muncul/hilang.
  var subs=(cur.res&&cur.res.subtitles)||[];
  if(cur.translate){
    var picked=pickSubtitleUrl(subs, "Indonesian");
    if(picked){
      cur.activeSub=picked;
      switchSubtitleTrack(picked);
    }
  }
  renderSubtitles(subs, cur.activeSub);
  toast("Translate: "+(cur.translate?"ON":"OFF"));
}

function renderSourceUI(){
  var s = cur.source || "hianime";
  var isOtaku = (s === "otakudesu");
  var isRebahin = (s === "rebahin");
  var isDutamovie = (s === "dutamovie" || s === "duta");
  var isFilm = (s === "film" || s === "movie");
  var txt = isOtaku ? "src: otakudesu (sub indo) ⇄" : (isRebahin ? "src: rebahin (sub indo) ⇄" : (isDutamovie ? "src: dutamovie21 (sub indo) ⇄" : (isFilm ? "src: film / tv (cinemeta) ⇄" : "src: hianime ⇄")));
  var badgeTxt = isOtaku ? "OTAKUDESU (SUB INDO) ⇄" : (isRebahin ? "REBAHIN (SUB INDO) ⇄" : (isDutamovie ? "DUTAMOVIE21 (SUB INDO) ⇄" : (isFilm ? "FILM / TV (CINEMETA) ⇄" : "HIANIME ⇄")));
  var sb = $("sb-source");
  if(sb){
    sb.textContent = txt;
    sb.classList.toggle("otaku", isOtaku);
    sb.classList.toggle("rebahin", isRebahin);
    sb.classList.toggle("dutamovie", isDutamovie);
    sb.classList.toggle("film", isFilm);
  }
  var tm = $("tm-source-btn");
  if(tm){
    tm.textContent = "SRC: " + badgeTxt;
    tm.classList.toggle("otaku", isOtaku);
    tm.classList.toggle("rebahin", isRebahin);
    tm.classList.toggle("dutamovie", isDutamovie);
    tm.classList.toggle("film", isFilm);
  }
  var b = $("drawer-src-badge");
  if(b){
    b.textContent = isOtaku ? "Otakudesu" : (isRebahin ? "Rebahin" : (isDutamovie ? "Dutamovie21" : (isFilm ? "Film / Cinema" : "HiAnime")));
  }
}

function switchSource(targetSource){
  var v=$("vid");
  var curTime = (v && !isNaN(v.currentTime)) ? v.currentTime : 0;
  var nextSource = targetSource;
  if(!nextSource){
    if(cur.source === "hianime") nextSource = "otakudesu";
    else if(cur.source === "otakudesu") nextSource = "rebahin";
    else if(cur.source === "rebahin") nextSource = "dutamovie";
    else if(cur.source === "dutamovie") nextSource = "film";
    else nextSource = "hianime";
  }
  cur.source = nextSource;
  renderSourceUI();
  if(window.Tatap && window.Tatap.setSetting){
    window.Tatap.setSetting({ preferred_source: nextSource }).catch(function(){});
  }
  var label = nextSource === "otakudesu" ? "Otakudesu (Sub Indo)" : (nextSource === "rebahin" ? "Rebahin (Sub Indo)" : (nextSource === "dutamovie" ? "Dutamovie21 (Sub Indo)" : (nextSource === "film" ? "Film & TV Series (Cinemeta)" : "HiAnime")));
  toast("Sumber: " + label);
  if(!$("player-modal").classList.contains("hidden") && cur.ep){
    openPlayer(cur.ep, curTime);
  }
  if($("genre-modal") && !$("genre-modal").classList.contains("hidden")){
    if(window.Tui && window.Tui.openGenreModal){
      window.Tui.openGenreModal();
    }
  }
  if(window.Tui && window.Tui.openSourceHome && (nextSource === "rebahin" || nextSource === "dutamovie")){
    window.Tui.openSourceHome(nextSource);
  } else if(window.Tui && window.Tui.loadView && (window.Tui.view && window.Tui.view() === "katalog")){
    window.Tui.loadView();
  }
  return nextSource;
}

function openDrawer(){
  var p = $("drawer-panel");
  if(p) p.classList.remove("hidden");
  // Update status di footer drawer
  var hEl = $("health");
  var dHText = $("drawer-health-text");
  if(dHText && hEl){
    dHText.textContent = hEl.textContent || "Online";
    dHText.className = hEl.className || "dim";
  }
}
function closeDrawer(){
  var p = $("drawer-panel");
  if(p) p.classList.add("hidden");
}

function openUpdateModal(data){
  var m = $("update-modal");
  if(!m) return;
  $("um-title").textContent = data.release_name || ("Tatap v" + data.latest_version);
  $("um-sub").textContent = "Rilis: " + (data.tag_name || "v" + data.latest_version) + " · Terpasang: v" + data.current_version;
  $("um-content").textContent = data.body || "Tidak ada catatan rilis.";
  
  var act = $("um-actions");
  act.innerHTML = "";
  
  // Deteksi OS user untuk tombol download utama
  var ua = (navigator.userAgent || "").toLowerCase();
  var isWin = ua.indexOf("windows") >= 0;
  var isLinux = ua.indexOf("linux") >= 0 && ua.indexOf("android") === -1;
  var isAndroid = ua.indexOf("android") >= 0;

  var primaryUrl = "";
  var primaryLabel = "Unduh Pembaruan";
  if(isWin && data.assets && data.assets.windows){
    primaryUrl = data.assets.windows;
    primaryLabel = "🪟 Unduh Windows Portable (.zip)";
  } else if(isLinux && data.assets && data.assets.linux){
    primaryUrl = data.assets.linux;
    primaryLabel = "🐧 Unduh Linux AppImage";
  } else if(isAndroid && data.assets && data.assets.android){
    primaryUrl = data.assets.android;
    primaryLabel = "📱 Unduh Signed APK Android";
  } else if(data.assets && data.assets.windows){
    primaryUrl = data.assets.windows;
    primaryLabel = "Unduh Rilis Resmi";
  }

  if(primaryUrl){
    var a = document.createElement("a");
    a.className = "update-btn";
    a.href = primaryUrl;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = primaryLabel;
    act.appendChild(a);
  }

  // Tombol buka halaman GitHub release
  if(data.release_url){
    var aRel = document.createElement("a");
    aRel.className = "update-btn secondary";
    aRel.href = data.release_url;
    aRel.target = "_blank";
    aRel.rel = "noopener noreferrer";
    aRel.textContent = "Buka di GitHub";
    act.appendChild(aRel);
  }

  m.classList.remove("hidden");
}

function closeUpdateModal(){
  var m = $("update-modal");
  if(m) m.classList.add("hidden");
}

function checkForUpdate(manualTrigger){
  if(manualTrigger) toast("Memeriksa update ke GitHub…", 2000);
  window.Tatap.checkUpdate().then(function(res){
    if(res && res.success && res.data){
      var d = res.data;
      if(d.has_update){
        openUpdateModal(d);
        toast("🚀 Pembaruan Tatap v" + d.latest_version + " tersedia!", 4000);
      } else {
        if(manualTrigger){
          toast("✓ Tatap v" + d.current_version + " adalah versi terbaru!", 3000);
        }
      }
    } else {
      if(manualTrigger){
        toast("Gagal memeriksa update: " + (res && res.error || "koneksi bermasalah"), 3000);
      }
    }
  }).catch(function(err){
    if(manualTrigger){
      toast("Error cek update: " + (err && err.message || err), 3000);
    }
  });
}

App = {
  openTitle:openTitle, openPlayer:openPlayer, playMPV:playMPV,
  renderContinue:renderContinue, onKeyPlayer:onKeyPlayer,
  switchSource:switchSource,
  openDrawer:openDrawer, closeDrawer:closeDrawer,
  openUpdateModal:openUpdateModal, closeUpdateModal:closeUpdateModal,
  checkForUpdate:checkForUpdate,
  openGenreModal:function(){
    if(typeof window.Tui!=="undefined"&&window.Tui.openGenreModal){
      window.Tui.openGenreModal();
    }
  }
};

function init(){
  loadPrefs();
  try{
    var sz=localStorage.getItem("tatap_subsize");
    if(sz==="s"||sz==="m"||sz==="l")cur.subSize=sz;
  }catch(e){}
  syncSubSize();
  // Toggle translate ID (persist localStorage tat_translate).
  try{
    var tr=localStorage.getItem("tatap_translate");
    if(tr==="1")cur.translate=true;
  }catch(e){}
  syncTranslate();
  var trBtn=$("pm-translate");
  if(trBtn) trBtn.addEventListener("click",function(){setTranslate(!cur.translate);});
  document.querySelectorAll(".sub-size button").forEach(function(b){
    b.addEventListener("click",function(){setSubSize(b.getAttribute("data-subsize"));});
  });
  var v=$("vid");
  if(v){
    v.addEventListener("timeupdate",paintCue);
    v.addEventListener("seeked",paintCue);
    v.addEventListener("fullscreenchange",syncFullscreenSubtitles);
    v.addEventListener("webkitfullscreenchange",syncFullscreenSubtitles);
    v.addEventListener("webkitbeginfullscreen",syncFullscreenSubtitles);
    v.addEventListener("webkitendfullscreen",syncFullscreenSubtitles);
    v.addEventListener("dblclick",function(e){
      e.preventDefault();
      toggleFullscreen();
    });
    if(!v._tatapFsHooked){
      v._tatapFsHooked=true;
      var origFs=v.requestFullscreen||v.webkitRequestFullscreen||v.mozRequestFullScreen||v.msRequestFullscreen;
      var fsHandler=function(options){
        var stage=document.querySelector(".ambient-stage");
        if(stage&&(stage.requestFullscreen||stage.webkitRequestFullscreen)){
          var p;
          try{
            if(stage.requestFullscreen)p=stage.requestFullscreen(options);
            else if(stage.webkitRequestFullscreen)p=stage.webkitRequestFullscreen(options);
            if(p&&p.catch){
              return p.catch(function(){
                if(origFs)return origFs.call(v,options);
                if(v.webkitEnterFullscreen)try{v.webkitEnterFullscreen();}catch(e){}
              });
            }
            return p;
          }catch(e){
            if(origFs)return origFs.call(v,options);
            if(v.webkitEnterFullscreen)try{v.webkitEnterFullscreen();}catch(err){}
          }
        }
        if(origFs)return origFs.call(v,options);
        if(v.webkitEnterFullscreen)try{v.webkitEnterFullscreen();}catch(e){}
      };
      if(v.requestFullscreen)v.requestFullscreen=fsHandler;
      if(v.webkitRequestFullscreen)v.webkitRequestFullscreen=fsHandler;
      if(v.mozRequestFullScreen)v.mozRequestFullScreen=fsHandler;
      if(v.msRequestFullscreen)v.msRequestFullscreen=fsHandler;
    }
  }
  document.addEventListener("fullscreenchange",syncFullscreenSubtitles);
  document.addEventListener("webkitfullscreenchange",syncFullscreenSubtitles);
  document.addEventListener("mozfullscreenchange",syncFullscreenSubtitles);
  document.addEventListener("MSFullscreenChange",syncFullscreenSubtitles);
  var pmFs=$("pm-fs");
  if(pmFs)pmFs.addEventListener("click",toggleFullscreen);
  renderSourceUI();
  var sbSrc=$("sb-source");
  if(sbSrc) sbSrc.addEventListener("click",function(){switchSource();});
  var tmSrc=$("tm-source-btn");
  if(tmSrc) tmSrc.addEventListener("click",function(){switchSource();});
  // Muat preferensi subtitle dari server (sub_lang). Kalau server gagal,
  // fallback ke default 'English' yang sudah di-set di var cur.
  if(window.Tatap&&window.Tatap.getSettings){
    window.Tatap.getSettings().then(function(r){
      if(r&&r.success&&r.data){
        if(r.data.sub_lang) cur.subLang=r.data.sub_lang;
        if(r.data.quality) cur.quality=r.data.quality;
        if(r.data.mode) {cur.mode=r.data.mode; syncSeg();}
        if(r.data.preferred_source) {
          cur.source=r.data.preferred_source;
          renderSourceUI();
          if((cur.source === "rebahin" || cur.source === "dutamovie") && window.Tui && window.Tui.openSourceHome){
            window.Tui.openSourceHome(cur.source);
          }
        }
      }
    }).catch(function(){});
  }
  document.querySelectorAll("#mode-seg button").forEach(function(b){
    b.addEventListener("click",function(){
      document.querySelectorAll("#mode-seg button").forEach(function(x){x.classList.remove("active");});
      b.classList.add("active");cur.mode=b.getAttribute("data-mode");loadEps();
    });
  });
  document.querySelectorAll("#quality-seg button").forEach(function(b){
    b.addEventListener("click",function(){
      document.querySelectorAll("#quality-seg button").forEach(function(x){x.classList.remove("active");});
      b.classList.add("active");cur.quality=b.getAttribute("data-q");
    });
  });
  $("ep-filter").addEventListener("input",renderEpGrid);
  $("tm-close").addEventListener("click",closeTitle);
  $("title-modal").addEventListener("click",function(e){if(e.target===this)closeTitle();});
  $("pm-close").addEventListener("click",closePlayer);
  $("player-modal").addEventListener("click",function(e){
    if(Date.now() - (cur.playerOpenedAt || 0) < 500) return;
    if(e.target===this) closePlayer();
  });
  $("pm-prev").addEventListener("click",function(){stepEp(-1);});
  $("pm-next").addEventListener("click",function(){stepEp(1);});
  $("pm-mpv").addEventListener("click",playMPV);
  var qSel=$("pm-quality-select");
  if(qSel){
    qSel.addEventListener("change",function(){
      switchQ(this.value);
    });
  }
  startAmbient();
  renderContinue();

  // Listener Drawer Navigation & Update Modal
  var btnDrawer = $("btn-drawer");
  if(btnDrawer) btnDrawer.addEventListener("click", openDrawer);
  var btnDrawerHead = $("btn-drawer-head");
  if(btnDrawerHead) btnDrawerHead.addEventListener("click", openDrawer);
  var btnDrawerClose = $("drawer-close");
  if(btnDrawerClose) btnDrawerClose.addEventListener("click", closeDrawer);
  var drawerBackdrop = $("drawer-backdrop");
  if(drawerBackdrop) drawerBackdrop.addEventListener("click", closeDrawer);

  // Navigasi Top Tabs (Header)
  document.querySelectorAll(".nav-tab[data-view]").forEach(function(b){
    b.addEventListener("click", function(){
      var v = b.getAttribute("data-view");
      if(window.Tui && window.Tui.setView){
        window.Tui.setView(v);
      }
    });
  });

  var topNavGenre = $("head-nav-genre");
  if(topNavGenre) {
    topNavGenre.addEventListener("click", function(){
      if(window.Tui && window.Tui.openGenreModal) window.Tui.openGenreModal();
    });
  }

  // CRT Scanlines Toggle with LocalStorage persistence
  var btnCrt = $("btn-theme-crt");
  if(btnCrt) {
    if(localStorage.getItem("tatap_no_crt") === "1") {
      document.body.classList.add("no-crt");
    }
    btnCrt.addEventListener("click", function(){
      var isNoCrt = document.body.classList.toggle("no-crt");
      localStorage.setItem("tatap_no_crt", isNoCrt ? "1" : "0");
      toast(isNoCrt ? "CRT scanlines dinonaktifkan" : "CRT scanlines aktif");
    });
  }

  // Navigasi menu di dalam Drawer
  document.querySelectorAll(".drawer-item[data-view]").forEach(function(b){
    b.addEventListener("click", function(){
      var v = b.getAttribute("data-view");
      closeDrawer();
      if(window.Tui && window.Tui.setView){
        window.Tui.setView(v);
      }
    });
  });

  var drawerGenre = $("drawer-genre");
  if(drawerGenre) drawerGenre.addEventListener("click", function(){
    closeDrawer();
    if(window.Tui && window.Tui.openGenreModal) window.Tui.openGenreModal();
  });

  var drawerSrc = $("drawer-switch-source");
  if(drawerSrc) drawerSrc.addEventListener("click", function(){
    switchSource();
    var b = $("drawer-src-badge");
    if(b) b.textContent = cur.source === "otakudesu" ? "Otakudesu" : (cur.source === "rebahin" ? "Rebahin" : (cur.source === "dutamovie" ? "Dutamovie21" : (cur.source === "film" ? "Film / Cinema" : "HiAnime")));
  });

  var drawerHelp = $("drawer-help");
  if(drawerHelp) drawerHelp.addEventListener("click", function(){
    closeDrawer();
    var ho = $("help-overlay");
    if(ho) ho.classList.remove("hidden");
    var hb = $("help-body");
    if(hb && window.Tui) hb.textContent = window.Tui.cmdUsage();
  });

  var drawerClearSearch = $("drawer-clear-search");
  if(drawerClearSearch) drawerClearSearch.addEventListener("click", function(){
    closeDrawer();
    if(window.Tui && window.Tui.clearAllRecents){
      window.Tui.clearAllRecents();
    } else {
      try { localStorage.removeItem("tatap_recent"); } catch(e){}
      toast("Riwayat pencarian dihapus");
    }
  });

  var drawerUpd = $("drawer-update");
  if(drawerUpd) drawerUpd.addEventListener("click", function(){
    closeDrawer();
    checkForUpdate(true);
  });

  var umClose = $("um-close");
  if(umClose) umClose.addEventListener("click", closeUpdateModal);
  var um = $("update-modal");
  if(um) um.addEventListener("click", function(e){
    if(e.target === um) closeUpdateModal();
  });

  window.Tui.boot();
}
init();