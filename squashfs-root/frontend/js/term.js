var Tui = (function () {
  var S = {view:"cari",items:[],sel:-1,page:1,total:1,filter:{},promptFoc:false,seasonFilter:null};
  var MAXLOG = 200;

  function $(id){return document.getElementById(id);}
  function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
  function isModalOpen(){
    return (!$("title-modal").classList.contains("hidden")) ||
           (!$("player-modal").classList.contains("hidden")) ||
           ($("drawer-panel") && !$("drawer-panel").classList.contains("hidden")) ||
           ($("update-modal") && !$("update-modal").classList.contains("hidden"));
  }

  function log(msg,kind){
    var box=$("log");box.classList.remove("hidden");
    var d=document.createElement("div");d.className="log-line"+(kind?" log-"+kind:"");
    d.textContent=msg;box.appendChild(d);
    while(box.children.length>MAXLOG) box.removeChild(box.firstChild);
    box.scrollTop=box.scrollHeight;
  }
  function clearLog(){$("log").classList.add("hidden");$("log").innerHTML="";}

  function loadRecents(){try{return JSON.parse(localStorage.getItem("tatap_recent")||"[]");}catch(e){return [];}}
  function loadCmdHist(){try{return JSON.parse(localStorage.getItem("tatap_hist")||"[]");}catch(e){return [];}}
  function saveCmdHist(h){try{localStorage.setItem("tatap_hist",JSON.stringify(h.slice(0,50)));}catch(e){}}

  function cmdUsage(){
    return "perintah:\n  cari <judul> | :musim | :lanjutan | :katalog\n  :terbaru | :season <winter|spring|summer|fall> <tahun>\n  :switch [hianime|otaku|rebahin|dutamovie|film] (ganti sumber streaming HiAnime / Otakudesu / Rebahin / Dutamovie21 / Film & Series)\n  :filter [key=val...] | :filter reset\n  :genre <slug|title> | :genre | :genre --list | :genre reset\n  :update (cek versi rilis terbaru secara on-demand)\n  :apikey <key> | :ollama <key> | :groq <key> | :gemini <key> | :model <nama> | :apiurl <url>\n  :logs | :crt on|off|toggle | :ambient on|off|toggle\n  :riwayat | :status | :bantuan | :q";
  }

  function applyFilter(){
    if(S.view!=="katalog"){log("filter hanya di katalog","err");return;}
    S.page=1;loadView();
  }

  S.scheduleDay = S.scheduleDay || "today";

  function updateScheduleChips(){
    document.querySelectorAll("#schedule-days-bar button").forEach(function(b){
      b.classList.toggle("active", b.getAttribute("data-day") === (S.scheduleDay || "today"));
    });
  }

  function setView(v){
    var curSrc = getActiveSource();
    var isMovieSrc = (curSrc === "rebahin" || curSrc === "dutamovie");
    if(isMovieSrc && (v === "musim" || v === "lanjutan" || v === "terbaru")){
      openSourceHome(curSrc);
      return;
    }
    S.view=v;S.page=1;S.sel=-1;S.items=[];clearLog();
    $("empty-state").style.display="none";
    $("results").innerHTML="";$("results-title").textContent="memuat...";$("results-meta").textContent="";
    $("pager").classList.add("hidden");
    $("lane-season-sec").classList.add("hidden");
    $("lane-still-sec").classList.add("hidden");
    var sBar = $("schedule-days-bar");
    if(sBar) sBar.classList.toggle("hidden", v !== "terbaru");
    if(v === "terbaru") updateScheduleChips();
    $("continue-sec").classList.add("hidden");
    document.querySelectorAll(".nav-tab[data-view]").forEach(function(tab){
      tab.classList.toggle("active", tab.getAttribute("data-view") === v);
    });
    switch(v){
      case "cari":$("results-title").textContent="cari judul";$("empty-state").style.display="";break;
      case "musim":$("results-title").textContent="Tayang musim ini";break;
      case "lanjutan":$("results-title").textContent="Masih tayang (lanjut)";break;
      case "katalog":{
        if(isMovieSrc){
          S.filter = { source: curSrc };
          $("results-title").textContent = "Film & Series Terbaru (" + (curSrc === "rebahin" ? "Rebahin" : "Dutamovie21") + ")";
        } else {
          $("results-title").textContent = "Katalog";
        }
        break;
      }
      case "terbaru":{
        var lblDay = S.scheduleDay === "yesterday" ? "kemarin" : (S.scheduleDay === "tomorrow" ? "besok" : "hari ini");
        $("results-title").textContent="Jadwal rilis (" + lblDay + ")";
        break;
      }
      case "season-custom":{
        var sf=S.seasonFilter||{season:"",year:""};
        $("results-title").textContent="Season: "+(sf.season||"?")+" "+sf.year;
        break;
      }
    }
    $("sb-view").textContent="view: "+v;
    loadView();
  }

  function apiCall(name){
    var curSrc = getActiveSource();
    var isMovieSrc = (curSrc === "rebahin" || curSrc === "dutamovie");
    if(isMovieSrc && (name === "musim" || name === "lanjutan" || name === "terbaru" || name === "katalog")){
      return window.Tatap.browse(S.filter, S.page);
    }
    switch(name){
      case "musim":return window.Tatap.seasonNow(S.page);
      case "lanjutan":return window.Tatap.stillAiring(S.page);
      case "katalog":return window.Tatap.browse(S.filter,S.page);
      case "terbaru":return window.Tatap.schedule(S.scheduleDay || "today");
      case "season-custom":{
        if(!S.seasonFilter)return null;
        return window.Tatap.seasonBy(S.seasonFilter.season, S.seasonFilter.year, S.page);
      }
      case "cari":return null;
    }
    return null;
  }

  async function loadView(){
    if(S.view==="cari"){renderRecents();return;}
    try{
      var r=await apiCall(S.view);
      if(!r){log("gagal load: response kosong","err");return;}
      if(!r.success){
        // FastAPI 422 unpacked — tampilkan detail pertama agar user tahu alasannya.
        var msg=r.error;
        if(Array.isArray(r.detail)&&r.detail[0]&&r.detail[0].msg){
          msg=r.detail[0].msg;
        }else if(r.detail&&r.detail.msg){
          msg=r.detail.msg;
        }
        log("gagal load: "+(msg||"??"),"err");
        return;
      }
      var d=r.data||{};
      S.items=d.items||[];S.page=d.page||1;S.total=d.total_pages||1;S.sel=-1;
      var baseTitle = "Tayang musim ini";
      var curSrc = (S.filter && S.filter.source) || (window.cur && window.cur.source) || "hianime";
      var srcName = curSrc === "rebahin" ? "Rebahin" : (curSrc === "dutamovie" ? "Dutamovie21" : "HiAnime");
      if(curSrc === "rebahin" || curSrc === "dutamovie"){
        if(S.filter && S.filter.genre){
          baseTitle = "Genre: " + S.filter.genre + " (" + srcName + ")";
        } else {
          baseTitle = "Film & Series Terbaru (" + srcName + ")";
        }
      } else {
        if(S.view === "lanjutan") baseTitle = "Masih tayang (lanjut)";
        else if(S.view === "katalog"){
          if(S.filter && S.filter.genre){
            baseTitle = "Genre: " + S.filter.genre + " (" + srcName + ")";
          } else {
            baseTitle = "Katalog (" + srcName + ")";
          }
        }
        else if(S.view === "terbaru"){
          var lblDay = S.scheduleDay === "yesterday" ? "kemarin" : (S.scheduleDay === "tomorrow" ? "besok" : "hari ini");
          baseTitle = "Jadwal rilis (" + lblDay + ")";
        } else if(S.view === "season-custom"){
          var sf = S.seasonFilter || {season:"", year:""};
          baseTitle = "Season: " + (sf.season || "?") + " " + sf.year;
        }
        if(d.season){
          baseTitle += " · " + String(d.season).toUpperCase() + (d.year ? " " + d.year : "");
        }
      }
      $("results-title").textContent = baseTitle;
      $("results-meta").textContent = S.items.length + " item" + (d.cached ? " · cached" : "");
      renderResults();renderPager();
    }catch(e){log("err: "+(e&&e.message||e),"err");}
  }

  function removeRecent(q){
    var recent = loadRecents().filter(function(x){ return x !== q; });
    try { localStorage.setItem("tatap_recent", JSON.stringify(recent)); } catch(e){}
    renderRecents();
    log("riwayat pencarian '" + q + "' dihapus", "ok");
    if(window.toast) window.toast("Pencarian dihapus");
  }

  function clearAllRecents(){
    try { localStorage.removeItem("tatap_recent"); } catch(e){}
    renderRecents();
    log("semua riwayat pencarian dihapus", "ok");
    if(window.toast) window.toast("Riwayat pencarian dihapus");
  }

  function renderRecents(){
    var curSrc = getActiveSource();
    var isMovieSrc = (curSrc === "rebahin" || curSrc === "dutamovie");
    S.items=[];S.sel=-1;var r=loadRecents();
    var box=$("results");box.innerHTML="";
    var sBar = $("schedule-days-bar");
    if(sBar) sBar.classList.add("hidden");
    var btnClear = $("clear-search-hist");
    if(!r.length){
      if(btnClear) btnClear.classList.add("hidden");
      if(isMovieSrc){
        openSourceHome(curSrc);
        return;
      }
      $("empty-state").style.display="";
      $("results-title").textContent="siap";
      $("results-meta").textContent="";
      $("pager").classList.add("hidden");
      return;
    }
    if(btnClear) btnClear.classList.remove("hidden");
    $("empty-state").style.display="none";
    $("results-title").textContent="saran pencarian";$("results-meta").textContent=r.length+" recent";
    for(var i=0;i<r.length;i++){
      (function(q, idx){
        var d=document.createElement("div");d.className="trow trow-recent";
        d.innerHTML='<span class="tr-num">'+(idx+1)+'</span><span class="tr-title">'+esc(q)+'</span><button class="tr-del-btn" title="Hapus riwayat \''+esc(q)+'\'" type="button" aria-label="Hapus">✕</button>';
        d.addEventListener("click",function(e){
          if(e.target && (e.target.classList.contains("tr-del-btn") || e.target.closest(".tr-del-btn"))) return;
          startSearch(q);
        });
        var delBtn = d.querySelector(".tr-del-btn");
        if(delBtn){
          delBtn.addEventListener("click", function(e){
            e.stopPropagation();
            removeRecent(q);
          });
        }
        box.appendChild(d);
      })(r[i], i);
    }
    if(isMovieSrc){
      var homeRow = document.createElement("div");
      homeRow.className = "trow trow-recent";
      homeRow.style.borderColor = "var(--acc)";
      homeRow.innerHTML = '<span class="tr-num">🎬</span><span class="tr-title" style="color:var(--acc);font-weight:600;">Lihat Beranda / Film Terbaru (' + (curSrc === "rebahin" ? "Rebahin" : "Dutamovie21") + ') &rarr;</span>';
      homeRow.addEventListener("click", function(){ openSourceHome(curSrc); });
      box.appendChild(homeRow);
    }
  }

  function renderResults(){
    var box=$("results");box.innerHTML="";
    var sBar = $("schedule-days-bar");
    if(sBar) sBar.classList.toggle("hidden", S.view !== "terbaru");
    var isTxt = S.view==="cari" || S.view==="terbaru";
    if(!S.items.length){box.innerHTML="<p class='dim'>Kosong.</p>";return;}
    if(isTxt){
      var nowTs=Math.floor(Date.now()/1000);
      for(var i=0;i<S.items.length;i++){
        (function(a,idx){
          if(S.view==="terbaru"){
            var d=document.createElement("div");
            var aheadSec=(a.airing_at||0)-nowTs;
            var cls="trow trow-up trow-media"+(idx===S.sel?" sel":"");
            if(aheadSec>0&&aheadSec<86400) cls+=" today";
            else if(aheadSec>=86400&&aheadSec<172800) cls+=" tomorrow";
            d.className=cls;

            // Thumbnail poster
            var thumbWrap=document.createElement("div");
            thumbWrap.className="tr-thumb-wrap";
            if(a.poster){
              var img=document.createElement("img");
              img.className="tr-thumb";
              img.loading="lazy";
              img.alt=a.title||"";
              img.src=a.poster;
              img.onerror=function(){
                this.style.display="none";
                thumbWrap.classList.add("no-img");
                var ph=document.createElement("span");
                ph.className="tr-thumb-ph";
                ph.textContent="▶";
                thumbWrap.appendChild(ph);
              };
              thumbWrap.appendChild(img);
            } else {
              thumbWrap.classList.add("no-img");
              var ph=document.createElement("span");
              ph.className="tr-thumb-ph";
              ph.textContent="▶";
              thumbWrap.appendChild(ph);
            }
            d.appendChild(thumbWrap);

            var metaCol=document.createElement("div");
            metaCol.className="tr-badge-col";
            var when=(a.date?a.date+" · ":"")+(a.time||"");
            var spanDay=document.createElement("span");
            spanDay.className="tr-day";
            spanDay.textContent=when;
            var spanEp=document.createElement("span");
            spanEp.className="tr-ep";
            spanEp.textContent="ep "+(a.episode==null||a.episode==undefined?"?":a.episode);
            metaCol.appendChild(spanDay);
            metaCol.appendChild(spanEp);
            d.appendChild(metaCol);

            var infoCol=document.createElement("div");
            infoCol.className="tr-info";
            var spanTitle=document.createElement("span");
            spanTitle.className="tr-title";
            spanTitle.textContent=a.title||"";
            infoCol.appendChild(spanTitle);

            if(a.type || a.score){
              var subMeta=document.createElement("div");
              subMeta.className="tr-meta";
              if(a.type){
                var chipType=document.createElement("span");
                chipType.className="badge-chip type";
                chipType.textContent=a.type;
                subMeta.appendChild(chipType);
              }
              if(a.score){
                var chipScore=document.createElement("span");
                chipScore.className="badge-chip score";
                chipScore.textContent="★ "+a.score;
                subMeta.appendChild(chipScore);
              }
              infoCol.appendChild(subMeta);
            }
            d.appendChild(infoCol);

            d.addEventListener("click",function(){
              if(typeof App==="undefined"){log("App belum siap, coba lagi","err");return;}
              App.openTitle(a.id,a.title);
            });
            box.appendChild(d);
          } else {
            var d2=document.createElement("div");
            d2.className="trow trow-media"+(idx===S.sel?" sel":"");

            var spanNum=document.createElement("span");
            spanNum.className="tr-num";
            spanNum.textContent=idx+1;
            d2.appendChild(spanNum);

            var thumbWrap2=document.createElement("div");
            thumbWrap2.className="tr-thumb-wrap";
            if(a.poster){
              var img2=document.createElement("img");
              img2.className="tr-thumb";
              img2.loading="lazy";
              img2.alt=a.title||"";
              img2.src=a.poster;
              img2.onerror=function(){
                this.style.display="none";
                thumbWrap2.classList.add("no-img");
                var ph2=document.createElement("span");
                ph2.className="tr-thumb-ph";
                ph2.textContent="▶";
                thumbWrap2.appendChild(ph2);
              };
              thumbWrap2.appendChild(img2);
            } else {
              thumbWrap2.classList.add("no-img");
              var ph2=document.createElement("span");
              ph2.className="tr-thumb-ph";
              ph2.textContent="▶";
              thumbWrap2.appendChild(ph2);
            }
            d2.appendChild(thumbWrap2);

            var infoCol2=document.createElement("div");
            infoCol2.className="tr-info";
            var spanTitle2=document.createElement("span");
            spanTitle2.className="tr-title";
            spanTitle2.textContent=a.title||"";
            infoCol2.appendChild(spanTitle2);

            var subMeta2=document.createElement("div");
            subMeta2.className="tr-meta";
            if(a.type){
              var cType=document.createElement("span");
              cType.className="badge-chip type";
              cType.textContent=a.type;
              subMeta2.appendChild(cType);
            }
            if(a.sub){
              var cSub=document.createElement("span");
              cSub.className="badge-chip sub";
              cSub.textContent="SUB "+a.sub;
              subMeta2.appendChild(cSub);
            }
            if(a.dub){
              var cDub=document.createElement("span");
              cDub.className="badge-chip dub";
              cDub.textContent="DUB "+a.dub;
              subMeta2.appendChild(cDub);
            }
            if(a.eps){
              var cEps=document.createElement("span");
              cEps.className="badge-chip";
              cEps.textContent=a.eps+" ep";
              subMeta2.appendChild(cEps);
            }
            infoCol2.appendChild(subMeta2);
            d2.appendChild(infoCol2);

            d2.addEventListener("click",function(){
              if(typeof App==="undefined"){log("App belum siap, coba lagi","err");return;}
              App.openTitle(a.id,a.title);
            });
            box.appendChild(d2);
          }
        })(S.items[i],i);
      }
    } else {
      var grid=document.createElement("div");grid.className="poster-grid";
      for(var j=0;j<S.items.length;j++){
        (function(a,idx){
          var isUnavail=!a.id;
          var d=document.createElement("div");
          d.className="poster-card"+(idx===S.sel?" sel":"")+(isUnavail?" unmapped":"");
          d.tabIndex=0;

          // Media container with exact proportional aspect ratio
          var media=document.createElement("div");
          media.className="pc-media";

          // Floating status badges top bar
          var badgesTop=document.createElement("div");
          badgesTop.className="pc-badges-top";
          var idxSpan=document.createElement("span");
          idxSpan.className="pc-badge idx";
          idxSpan.textContent="#"+String(idx+1).padStart(2,"0");
          badgesTop.appendChild(idxSpan);

          if(a.score){
            var scoreBadge=document.createElement("span");
            scoreBadge.className="pc-badge score";
            scoreBadge.textContent="★ "+Number(a.score).toFixed(1);
            badgesTop.appendChild(scoreBadge);
          } else if(a.type){
            var typeBadge=document.createElement("span");
            typeBadge.className="pc-badge type";
            typeBadge.textContent=a.type;
            badgesTop.appendChild(typeBadge);
          }
          media.appendChild(badgesTop);

          if(isUnavail){
            var bad=document.createElement("span");
            bad.className="pc-bad";
            bad.textContent="?";
            bad.title="Tidak ada di hianime";
            media.appendChild(bad);
          }

          if(a.poster){
            var im=document.createElement("img");
            im.loading="lazy";
            im.alt=a.title||"";
            im.src=a.poster;
            im.onerror=function(){this.style.display="none";};
            media.appendChild(im);
          }

          var vig=document.createElement("div");
          vig.className="pc-vignette";
          media.appendChild(vig);

          var playBtn=document.createElement("div");
          playBtn.className="pc-play-btn";
          var playIcon=document.createElement("span");
          playIcon.className="pc-play-icon";
          playIcon.textContent="▶";
          playBtn.appendChild(playIcon);
          media.appendChild(playBtn);

          d.appendChild(media);

          // Poster Body
          var body=document.createElement("div");
          body.className="poster-body";
          var b=document.createElement("b");
          b.textContent=a.title||"";
          b.title=a.title||"";
          body.appendChild(b);

          var meta=document.createElement("div");
          meta.className="poster-meta";
          if(a.type){
            var pType=document.createElement("span");
            pType.className="poster-meta-pill accent";
            pType.textContent=a.type;
            meta.appendChild(pType);
          }
          if(a.sub){
            var pSub=document.createElement("span");
            pSub.className="poster-meta-pill";
            pSub.textContent="SUB "+a.sub;
            meta.appendChild(pSub);
          } else if(a.eps){
            var pEps=document.createElement("span");
            pEps.className="poster-meta-pill";
            pEps.textContent=a.eps+" ep";
            meta.appendChild(pEps);
          }
          if(a.duration){
            var pDur=document.createElement("span");
            pDur.className="poster-meta-pill";
            pDur.textContent=a.duration;
            meta.appendChild(pDur);
          }
          body.appendChild(meta);
          d.appendChild(body);

          if(!isUnavail){
            d.addEventListener("click",function(){App.openTitle(a.id,a.title);});
          }
          grid.appendChild(d);
        })(S.items[j],j);
      }
      box.appendChild(grid);
    }
  }

  function goToPage(p){
    p = parseInt(p, 10);
    if(isNaN(p) || p < 1 || p === S.page) return;
    if(S.total && p > S.total) return;
    S.page = p;
    var resBox = $("results");
    if(resBox) {
      resBox.scrollIntoView({behavior: "smooth", block: "start"});
    }
    loadView();
  }

  function renderPager(){
    var pager = $("pager");
    if(!pager) return;
    var show = S.view !== "cari" && S.items && S.items.length > 0;
    pager.classList.toggle("hidden", !show);
    if(!show) return;

    var cur = S.page || 1;
    var tot = Math.max(1, S.total || 1);

    var prevBtn = $("pg-prev");
    var nextBtn = $("pg-next");
    var pagesBox = $("pg-pages");
    var infoSpan = $("pg-info");

    if(prevBtn){
      prevBtn.disabled = cur <= 1;
      prevBtn.onclick = function(){
        if(S.page > 1) goToPage(S.page - 1);
      };
    }

    if(nextBtn){
      nextBtn.disabled = cur >= tot;
      nextBtn.onclick = function(){
        if(S.page < tot) goToPage(S.page + 1);
      };
    }

    if(pagesBox){
      pagesBox.innerHTML = "";
      if(tot > 1){
        var pages = [];
        if(tot <= 7){
          for(var i = 1; i <= tot; i++) pages.push(i);
        } else {
          pages.push(1);
          if(cur > 3) pages.push("...");
          var start = Math.max(2, cur - 1);
          var end = Math.min(tot - 1, cur + 1);
          for(var p = start; p <= end; p++){
            if(pages.indexOf(p) === -1) pages.push(p);
          }
          if(cur < tot - 2) pages.push("...");
          if(pages.indexOf(tot) === -1) pages.push(tot);
        }

        pages.forEach(function(p){
          if(p === "..."){
            var el = document.createElement("span");
            el.className = "pager-ellipsis";
            el.textContent = "…";
            pagesBox.appendChild(el);
          } else {
            var btn = document.createElement("button");
            btn.className = "pager-page-btn" + (p === cur ? " active" : "");
            btn.type = "button";
            btn.textContent = p;
            btn.title = "Ke halaman " + p;
            btn.onclick = (function(pageNum){
              return function(){ goToPage(pageNum); };
            })(p);
            pagesBox.appendChild(btn);
          }
        });
      }
    }

    if(infoSpan){
      infoSpan.textContent = tot > 1 ? ("Hal " + cur + " dari " + tot + " · [ ]") : (S.items.length + " item");
    }
  }

  function moveSel(d){
    if(!S.items.length)return;
    S.sel=(S.sel+d+S.items.length)%S.items.length;
    renderSel();
  }
  function renderSel(){
    var box=$("results");
    var all=box.querySelectorAll(".trow");
    for(var i=0;i<all.length;i++){
      var isUnm=all[i].classList.contains("unmapped");
      all[i].classList.toggle("sel",i===S.sel&&!isUnm);
    }
    if(all[S.sel])all[S.sel].scrollIntoView({block:"nearest"});
  }
  function openSelected(){
    if(!S.items.length)return;
    var a=S.items[S.sel];
    if(!a||!a.id){log("judul ini belum tersedia di hianime","err");return;}
    App.openTitle(a.id,a.title);
  }

  function startSearch(q){
    q=q.trim();if(!q)return;
    var recent=loadRecents().filter(function(x){return x!==q;});recent.unshift(q);
    try{localStorage.setItem("tatap_recent",JSON.stringify(recent.slice(0,6)));}catch(e){}
    setViewSilent("cari");
    $("empty-state").style.display="none";
    $("results-title").textContent="Mencari "+q+"...";$("results-meta").textContent="";
    doSearch(q);
  }

  async function doSearch(q){
    var btnClear = $("clear-search-hist");
    if(btnClear) btnClear.classList.add("hidden");
    var t0=Date.now();
    try{
      var src = (window.cur && window.cur.source) || "";
      var r = await window.Tatap.search(q, src);
      if(!r||!r.success){log("search error: "+(r&&r.error||"??"),"err");return;}
      S.items=r.data.results||[];S.sel=-1;S.total=1;
      $("results-title").textContent=S.items.length?"Hasil untuk \""+q+"\"":"Tidak ketemu \""+q+"\"";
      $("results-meta").textContent=S.items.length+" judul · "+(Date.now()-t0)+"ms"+(r.data.cached?" · cached":"");
      renderResults();renderPager();
    }catch(e){log("err: "+e.message,"err");}
  }

  function setViewSilent(v){
    S.view=v;S.page=1;
    $("pager").classList.add("hidden");
    $("continue-sec").classList.add("hidden");
    $("lane-season-sec").classList.add("hidden");
    $("lane-still-sec").classList.add("hidden");
    var sBar = $("schedule-days-bar");
    if(sBar) sBar.classList.toggle("hidden", v !== "terbaru");
  }

  // ==== :genre ====
  var _genreCache={};
  function getActiveSource(){
    return (window.cur && window.cur.source) || "hianime";
  }
  function slugifyGenre(s){
    return String(s||"").trim().toLowerCase()
      .replace(/&/g,"and").replace(/[^a-z0-9]+/g,"-")
      .replace(/^-+|-+$/g,"");
  }
  async function loadGenres(forceSource){
    var curSrc = forceSource || getActiveSource();
    if(curSrc === "otakudesu") curSrc = "hianime";
    if(_genreCache[curSrc] && _genreCache[curSrc].length) return _genreCache[curSrc];
    var r = await window.Tatap.genres(curSrc);
    var raw = (r && r.success && r.data && r.data.list) || [];
    _genreCache[curSrc] = raw;
    return _genreCache[curSrc];
  }
  async function openGenreModal(){
    var curSrc = getActiveSource();
    var srcName = curSrc === "rebahin" ? "Rebahin" : (curSrc === "dutamovie" ? "Dutamovie21" : (curSrc === "otakudesu" ? "HiAnime / Otakudesu" : "HiAnime"));
    var headEl = document.querySelector("#genre-modal .sec-head h2");
    if(headEl) headEl.textContent = "Pilih Genre (" + srcName + ")";
    var sInp = $("genre-search");
    if(sInp){
      sInp.value = "";
      sInp.placeholder = (curSrc === "rebahin" || curSrc === "dutamovie") ? "Cari genre… cth: action" : "Cari genre… cth: isekai";
    }
    $("genre-modal").classList.remove("hidden");
    var list = await loadGenres(curSrc);
    renderGenreList(list, curSrc);
    setTimeout(function(){if($("genre-search"))$("genre-search").focus();}, 30);
  }
  function closeGenreModal(){$("genre-modal").classList.add("hidden");}
  function renderGenreList(list, source){
    var curSrc = source || getActiveSource();
    var box = $("genre-list"); box.innerHTML = "";
    if(!list.length){
      var e = document.createElement("div"); e.className = "empty"; e.textContent = "(tidak ada hasil)"; box.appendChild(e); return;
    }
    for(var i=0; i<list.length; i++){
      (function(g){
        var b = document.createElement("button");
        b.innerHTML = '<span class="g-slug">' + esc(g.slug) + '</span><span class="g-title">' + esc(g.title) + '</span>';
        b.addEventListener("click", function(){
          applyGenreFilter(g.slug, curSrc); closeGenreModal();
        });
        box.appendChild(b);
      })(list[i]);
    }
  }
  function applyGenreFilter(slug, source){
    var curSrc = source || getActiveSource();
    S.filter = {genre: slug, source: curSrc}; S.page = 1;
    log("genre (" + curSrc + "): " + slug, "ok");
    setViewSilent("katalog");
    var srcName = curSrc === "rebahin" ? "Rebahin" : (curSrc === "dutamovie" ? "Dutamovie21" : "HiAnime");
    $("results-title").textContent = "Genre: " + slug + " (" + srcName + ")";
    $("empty-state").style.display = "none";
    $("pager").classList.remove("hidden");
    loadView();
  }

  function openSourceHome(source){
    var curSrc = source || getActiveSource();
    var srcName = curSrc === "rebahin" ? "Rebahin" : (curSrc === "dutamovie" ? "Dutamovie21" : "HiAnime");
    S.filter = { source: curSrc };
    S.page = 1;
    S.sel = -1;
    S.items = [];
    S.view = "katalog";
    document.querySelectorAll(".nav-tab[data-view]").forEach(function(tab){
      tab.classList.toggle("active", tab.getAttribute("data-view") === "katalog");
    });
    $("empty-state").style.display = "none";
    var sBar = $("schedule-days-bar");
    if(sBar) sBar.classList.add("hidden");
    var btnClear = $("clear-search-hist");
    if(btnClear) btnClear.classList.add("hidden");
    $("results").innerHTML = "<p class='dim'>Memuat beranda " + srcName + "…</p>";
    $("results-title").textContent = "Film & Series Terbaru (" + srcName + ")";
    $("results-meta").textContent = "memuat…";
    $("pager").classList.remove("hidden");
    $("sb-view").textContent = "view: beranda (" + curSrc + ")";
    loadView();
  }
  async function cmdGenre(parts){
    var curSrc = getActiveSource();
    if(parts.length <= 1){ openGenreModal(); return; }
    var a = parts.slice(1);
    if(a[0] === "reset"){
      if(S.filter && S.filter.genre){
        delete S.filter.genre; delete S.filter.source; S.page = 1;
        log("genre filter dihapus", "ok"); applyFilter();
      }
      else log("tidak ada genre filter aktif", "err");
      return;
    }
    if(a[0] === "--list" || a[0] === "list"){
      var kw = a[1] && a[1] !== "--search" ? a[1] : (a[2] || "");
      var list = await loadGenres(curSrc);
      if(!list.length){ log("gagal load genre " + curSrc + " (offline?).", "err"); return; }
      var shown = 0;
      var srcName = curSrc === "rebahin" ? "Rebahin" : (curSrc === "dutamovie" ? "Dutamovie21" : "HiAnime");
      log("--- Daftar Genre: " + srcName + " ---", "ok");
      for(var i=0; i<list.length; i++){
        var g = list[i];
        if(kw && (g.title + " " + g.slug).toLowerCase().indexOf(kw.toLowerCase()) < 0) continue;
        log(("" + g.slug).padEnd(28) + "  " + g.title);
        shown++;
      }
      if(!shown) log("tidak ada genre cocok '" + kw + "'", "err");
      else log("total: " + shown + " genre", "ok");
      return;
    }
    var slug = slugifyGenre(a.join(" "));
    if(!slug){ log("usage: genre <slug|title> | genre | genre --list | genre reset", "err"); return; }
    applyGenreFilter(slug, curSrc);
  }

  // ==== :season ====
  var SEASONS = ["winter","spring","summer","fall"];
  function applySeasonFilter(name, year){
    S.seasonFilter = {season: name, year: year};
    S.page = 1;
    log("season: "+name+" "+year, "ok");
    setViewSilent("season-custom");
    $("results-title").textContent = "Season: "+name[0].toUpperCase()+name.slice(1)+" "+year;
    $("empty-state").style.display = "none";
    $("pager").classList.remove("hidden");
    loadView();
  }
  function cmdSeason(rawArgs){
    var t = (rawArgs||"").trim();
    if(!t){
      log("usage: season <winter|spring|summer|fall> <tahun>","err");
      log("contoh: :season fall 2024","err");return;
    }
    var parts = t.split(/\s+/);
    if(parts.length < 2){
      log("usage: season <winter|spring|summer|fall> <tahun>","err");
      log("contoh: :season fall 2024","err");return;
    }
    var name = parts[0].toLowerCase();
    var year = parseInt(parts[1], 10);
    if(SEASONS.indexOf(name) < 0){
      log("season tak dikenal: "+name+" (winter/spring/summer/fall)","err");return;
    }
    if(!year || year < 1900 || year > 2100){
      log("tahun tak valid: "+parts[1],"err");return;
    }
    applySeasonFilter(name, year);
  }

  // ==== :apikey / :model / :apiurl / :ollama / :groq / :gemini ====
  var TRANSLATE_KEYS = {
    apikey: {field:"translate_apikey", label:"apikey"},
    ollama: {field:"translate_apikey", label:"apikey (Ollama Cloud)"},
    groq:   {field:"translate_apikey", label:"apikey (Groq)"},
    gemini: {field:"translate_apikey", label:"apikey (Google AI Studio)"},
    openai: {field:"translate_apikey", label:"apikey (OpenAI)"},
    model:  {field:"translate_model",  label:"model"},
    apiurl: {field:"translate_apiurl", label:"apiurl"}
  };
  function maskKey(v){
    if(!v) return "(kosong)";
    if(v.length <= 10) return "****";
    var prefixLen = (v.indexOf("AQ.") === 0) ? 6 : 8;
    return v.slice(0, prefixLen) + "..." + v.slice(-4);
  }
  async function cmdTranslateSetting(cmd, rawArgs){
    var info = TRANSLATE_KEYS[cmd];
    if(!info) return;
    var args = (rawArgs||"").trim();
    if(cmd === "apikey" || cmd === "ollama" || cmd === "groq" || cmd === "gemini" || cmd === "openai"){
      args = args.replace(/^["']|["']$/g, "").trim();
    }
    if(!args){
      // Status: tampilkan ketiga nilai translate (mask apikey).
      var r = await window.Tatap.getSettings();
      var d = (r && r.success && r.data) || {};
      log("apikey : "+maskKey(d.translate_apikey||""),"ok");
      log("model  : "+(d.translate_model||"(default)"),"ok");
      log("apiurl : "+(d.translate_apiurl||"(default)"),"ok");
      if(!d.translate_apikey){
        log("Belum ada API key AI. Preset otomatis yang didukung:", "err");
        log("  • Ollama Cloud : :apikey <key>     (gratis, model: gpt-oss:20b)", "dim");
        log("  • Groq (Gratis) : :apikey gsk_...    (model: llama-3.3-70b-versatile)", "dim");
        log("  • Google AI     : :apikey AQ...      (model: gemini-3.1-flash-lite)", "dim");
        log("  • OpenAI        : :apikey sk-...      (model: gpt-4o-mini)", "dim");
      }
      return;
    }
    if(args === "clear" || args === "reset"){
      var p1 = {}; p1[info.field] = "";
      try{ await window.Tatap.setSetting(p1); }catch(e){}
      log(info.label+" dihapus","ok");
      return;
    }
    // Set value.
    var payload = {};
    payload[info.field] = args;
    var extra = "";
    if(cmd === "apikey" || cmd === "ollama" || cmd === "groq" || cmd === "gemini" || cmd === "openai"){
      // Deteksi Ollama Cloud:
      // 1) Command eksplisit :ollama
      // 2) Prefix: ollama_... atau ol_...
      // 3) Format API key resmi Ollama Cloud: 32 karakter hex + titik + alphanumeric secret token (misal: afd1045d...TYA04...)
      var isOllamaKey = cmd === "ollama" ||
                        args.indexOf("ollama_") === 0 ||
                        args.indexOf("ol_") === 0 ||
                        /^[a-f0-9]{32}\.[A-Za-z0-9_-]+$/.test(args);

      if(isOllamaKey){
        payload.translate_apiurl = "https://ollama.com/v1";
        payload.translate_model = "gpt-oss:20b";
        extra = " (auto: apiurl=Ollama Cloud, model=gpt-oss:20b, cadangan gpt-oss:120b)";
      }else if(cmd === "gemini" || args.indexOf("AQ.") === 0 || args.indexOf("AIza") === 0 || args.indexOf("AQ") === 0){
        // Google Gemini key (Google AI Studio: AQ. baru / AIza legacy) -> auto-set apiurl + model Gemini Flash Lite.
        payload.translate_apiurl = "https://generativelanguage.googleapis.com/v1beta/openai";
        payload.translate_model = "gemini-3.1-flash-lite";
        extra = " (auto: apiurl=Google AI Studio, model=gemini-3.1-flash-lite)";
      }else if(cmd === "groq" || args.indexOf("gsk_") === 0){
        // Groq key -> auto-set apiurl + model Llama-3.3-70B
        payload.translate_apiurl = "https://api.groq.com/openai/v1";
        payload.translate_model = "llama-3.3-70b-versatile";
        extra = " (auto: apiurl=Groq, model=llama-3.3-70b-versatile)";
      }else if(args.indexOf("sk-or-") === 0){
        payload.translate_apiurl = "https://openrouter.ai/api/v1";
        payload.translate_model = "google/gemini-2.0-flash-exp:free";
        extra = " (auto: apiurl=OpenRouter, model=gemini-2.0-flash-exp:free)";
      }else if(cmd === "openai" || args.indexOf("sk-") === 0 || args.indexOf("sk_") === 0){
        payload.translate_apiurl = "https://api.openai.com/v1";
        payload.translate_model = "gpt-4o-mini";
        extra = " (auto: apiurl=OpenAI, model=gpt-4o-mini)";
      }else{
        extra = " (provider kustom: gunakan juga :apiurl <url> dan :model <nama> bila perlu, atau ketik :ollama <key>)";
      }
    }
    try{
      var res = await window.Tatap.setSetting(payload);
      if(res && res.success){
        var masked = (cmd === "apikey") ? (" (" + maskKey(args) + ")") : (" (" + args + ")");
        log(info.label + " disimpan" + masked + extra, "ok");
      }else{
        log("gagal menyimpan " + info.label + ": " + ((res && res.error) || "unknown error"), "err");
      }
    }catch(e){
      log("gagal menyimpan " + info.label + ": " + e.message, "err");
    }
  }

  async function cmdLogs(){
    try{
      var r = await fetch("/api/translate/logs").then(function(res){return res.json();});
      var logs = (r&&r.data&&r.data.logs)||[];
      if(!logs.length){
        log("Belum ada riwayat aktivitas translasi subtitle.", "dim");
        return;
      }
      log("--- Riwayat Log Translasi Subtitle ---", "ok");
      for(var i=0; i<logs.length; i++){
        var line = logs[i];
        var cls = "dim";
        if(line.indexOf("sukses")>=0 || line.indexOf("selesai")>=0 || line.indexOf("Cache HIT")>=0){
          cls = "ok";
        }else if(line.indexOf("GAGAL")>=0 || line.indexOf("gagal")>=0 || line.indexOf("ERROR")>=0 || line.indexOf("Rate limit")>=0){
          cls = "err";
        }
        log(line, cls);
      }
    }catch(e){
      log("Gagal membaca log translasi: " + e.message, "err");
    }
  }

  async function handleCommand(raw){
    var s=raw.trim();if(!s)return;
    var parts=s.split(/\s+/);
    var cmd=parts[0].toLowerCase();
    var args=parts.slice(1).join(" ");
    switch(cmd){
      case "cari":if(!args){log("usage: cari <judul>","err");}else{startSearch(args);}break;
      case "musim":setView("musim");break;
      case "lanjutan":setView("lanjutan");break;
      case "katalog":setView("katalog");break;
      case "season":cmdSeason(args);break;
      case "terbaru":case "airing":setView("terbaru");break;
      case "switch":
        var target = (args || "").toLowerCase().trim();
        var curSrc = (window.cur && window.cur.source) || "hianime";
        var nxt = "";
        if(target === "otaku" || target === "otakudesu"){
          nxt = "otakudesu";
        }else if(target === "rebahin" || target === "rb"){
          nxt = "rebahin";
        }else if(target === "dutamovie" || target === "duta" || target === "dm21"){
          nxt = "dutamovie";
        }else if(target === "film" || target === "movie" || target === "movies"){
          nxt = "film";
        }else if(target === "hi" || target === "hianime"){
          nxt = "hianime";
        }else if(!target){
          if(curSrc === "hianime") nxt = "otakudesu";
          else if(curSrc === "otakudesu") nxt = "rebahin";
          else if(curSrc === "rebahin") nxt = "dutamovie";
          else if(curSrc === "dutamovie") nxt = "film";
          else nxt = "hianime";
        }else{
          log("usage: :switch [hianime|otaku|rebahin|dutamovie|film]","err");
          break;
        }
        if(window.App && window.App.switchSource){
          var resSrc = window.App.switchSource(nxt);
          var srcName = resSrc === "otakudesu" ? "Otakudesu (Sub Indo)" : (resSrc === "rebahin" ? "Rebahin (Sub Indo)" : (resSrc === "dutamovie" ? "Dutamovie21 (Sub Indo)" : (resSrc === "film" ? "Film & Series (Cinemeta)" : "HiAnime")));
          log("sumber streaming beralih ke: " + srcName, "ok");
          if(!$("genre-modal").classList.contains("hidden")){
            openGenreModal();
          }
        }else{
          if(window.Tatap && window.Tatap.setSetting){
            window.Tatap.setSetting({ preferred_source: nxt }).catch(function(){});
          }
          log("sumber streaming default: " + nxt, "ok");
        }
        break;
      case "genre":cmdGenre(parts);break;
      case "filter":
        if(!args||args==="reset"){
          S.filter={};S.page=1;log("filter direset","ok");applyFilter();break;
        }
        var f={};
        for(var i=0;i<parts.length-1;i++){
          var kv=parts[i+1].split("=");
          if(kv.length===2)f[kv[0]]=kv[1];
        }
        S.filter=f;S.page=1;log("filter: "+JSON.stringify(f),"ok");applyFilter();break;
      case "crt":
        if(!args){log("usage: crt on|off|toggle","err");break;}
        var v1=args==="on"?"on":args==="off"?"off":null;
        if(v1===null&&args!=="toggle"){log("usage: crt on|off|toggle","err");break;}
        var cur=localStorage.getItem("tatap_crt")||"on";
        var nxt=v1||(cur==="on"?"off":"on");
        try{localStorage.setItem("tatap_crt",nxt);}catch(e){}
        document.body.classList.toggle("no-crt",nxt==="off");
        log("crt "+(nxt==="on"?"ON":"OFF"),"ok");break;
      case "ambient":
        if(!args){log("usage: ambient on|off|toggle","err");break;}
        var v2=args==="on"?"on":args==="off"?"off":null;
        if(v2===null&&args!=="toggle"){log("usage: ambient on|off|toggle","err");break;}
        var cur2=localStorage.getItem("tatap_ambient")||"on";
        var nxt2=v2||(cur2==="on"?"off":"on");
        try{localStorage.setItem("tatap_ambient",nxt2);}catch(e){}
        document.body.classList.toggle("no-ambient",nxt2==="off");
        log("ambient "+(nxt2==="on"?"ON":"OFF"),"ok");break;
      case "riwayat":
        try{await fetch("/api/history",{method:"DELETE"});log("riwayat dihapus","ok");}catch(e){log("err: "+e.message,"err");}break;
      case "logs":case "translog":
        await cmdLogs();break;
      case "apikey":case "model":case "apiurl":
      case "ollama":case "groq":case "gemini":case "openai":
        await cmdTranslateSetting(cmd,args);break;
      case "server":
        if(!args){
          var curSrv = localStorage.getItem("tatap_server") || (location.origin && location.origin !== "null" ? location.origin : "http://127.0.0.1:8767");
          log("server backend saat ini: " + curSrv, "ok");
          log("usage: :server <http://ip-komputer:8767> atau :server reset", "dim");
        }else if(args === "reset" || args === "local"){
          localStorage.removeItem("tatap_server");
          log("server backend direset ke default (local)", "ok");
          location.reload();
        }else{
          var sUrl = args.trim().replace(/\/+$/, "");
          if(!/^https?:\/\//i.test(sUrl)) sUrl = "http://" + sUrl;
          localStorage.setItem("tatap_server", sUrl);
          log("server backend disetel ke: " + sUrl, "ok");
          setTimeout(function(){ location.reload(); }, 600);
        }
        break;
      case "status":
        var extra="";
        if(S.filter&&Object.keys(S.filter).length) extra+=" filter="+JSON.stringify(S.filter);
        if(S.seasonFilter) extra+=" season="+S.seasonFilter.season+" "+S.seasonFilter.year;
        log("view="+S.view+" page="+S.page+"/"+S.total+" items="+S.items.length+(S.sel>=0?" sel="+S.sel:"")+extra,"ok");break;
      case "update":case "upgrade":
        log("memeriksa rilis terbaru ke GitHub...","dim");
        if(window.App && window.App.checkForUpdate){
          window.App.checkForUpdate(true);
        } else {
          try{
            var ures = await window.Tatap.checkUpdate();
            if(ures && ures.success && ures.data){
              if(ures.data.has_update){
                log("pembaruan tersedia: v" + ures.data.latest_version + " — " + ures.data.release_name,"ok");
                log("kunjungi: " + ures.data.release_url,"ok");
              } else {
                log("Tatap v" + ures.data.current_version + " adalah versi terbaru. Tidak ada update.","ok");
              }
            } else {
              log("gagal cek update: " + (ures&&ures.error||"unknown"),"err");
            }
          }catch(err){
            log("koneksi gagal: " + (err&&err.message||err),"err");
          }
        }
        break;
      case "bantuan":case "help":case "?":
        $("help-overlay").classList.remove("hidden");
        $("help-body").textContent=cmdUsage();
        break;
      case "q":case "clear":
        $("cmd").value="";clearLog();break;
      default:
        if(cmd.indexOf(":")===0){log("perintah tak dikenal: "+cmd+"  (ketik :bantuan)","err");}
        else{startSearch(s);}
    }
  }

  function onKey(e){
    var t=(e.target.tagName||"");
    var typing = t==="INPUT"||t==="SELECT"||t==="TEXTAREA";
    if(e.key==="Escape"){
      if(isModalOpen()){App.onKeyPlayer(e);return;}
      if(typing){$("cmd").blur();S.promptFoc=false;return;}
      $("cmd").value="";clearLog();e.preventDefault();return;
    }
    if(isModalOpen()){App.onKeyPlayer(e);return;}
    if(e.key==="/"){e.preventDefault();focusPrompt();return;}
    if(typing){if(e.key==="Escape"){$("cmd").blur();S.promptFoc=false;}return;}
    if(e.key==="Escape"){$("cmd").value="";clearLog();e.preventDefault();return;}
    if(e.key==="Tab"){e.preventDefault();cycleView();return;}
    if(e.key==="ArrowUp"){
      e.preventDefault();
      if(!S.items.length){cmdHistory(-1);}else{moveSel(-1);}
      return;
    }
    if(e.key==="ArrowDown"){
      e.preventDefault();
      if(!S.items.length){cmdHistory(1);}else{moveSel(1);}
      return;
    }
    if(e.key==="Enter"){
      e.preventDefault();
      if(S.promptFoc){submitPrompt();}else{focusPrompt();}
      return;
    }
    if(e.key==="["||e.key===","){e.preventDefault();pagePrev();return;}
    if(e.key==="]"||e.key==="."){e.preventDefault();pageNext();return;}
    if(!typing&&e.key.length===1&&!e.ctrlKey&&!e.metaKey){focusPrompt();}
  }

  function focusPrompt(){
    S.promptFoc=true;
    var inp=$("cmd");inp.focus();
  }
  function submitPrompt(){
    var inp=$("cmd");var raw=inp.value.trim();inp.value="";
    if(!raw)return;
    log("tatap$ "+raw);
    if(raw.indexOf(":")===0){handleCommand(raw.slice(1));}
    else{handleCommand("cari "+raw);}
  }

  var _hIdx=0,_hPos=0;
  function cmdHistory(dir){
    var h=loadCmdHist();if(!h.length)return;
    _hPos+=dir;
    if(_hPos<0)_hPos=0;
    if(_hPos>=h.length)_hPos=h.length-1;
    $("cmd").value=h[_hPos]||"";
    var inp=$("cmd");inp.selectionStart=inp.selectionEnd=inp.value.length;
  }
  function cycleView(){
    var ord=["cari","musim","terbaru","lanjutan","katalog"];
    var idx=ord.indexOf(S.view);setView(ord[(idx+1)%ord.length]);
  }
  function pagePrev(){if(S.page>1){goToPage(S.page-1);}}
  function pageNext(){if(S.page<S.total){goToPage(S.page+1);}}

  function onPromptFocus(){S.promptFoc=true;$("cmd").classList.add("focus");}
  function onPromptBlur(){S.promptFoc=false;$("cmd").classList.remove("focus");setTimeout(function(){if($("cmd").value.trim()&&S.items.length){/* keep sel visible */}},50);}

  function boot(){
    var inp=$("cmd");
    inp.addEventListener("keydown",function(e){
      if(e.key==="Enter"){e.preventDefault();_hPos=loadCmdHist().length;submitPrompt();}
      else if(e.key==="Escape"){inp.blur();}
      else if(e.key==="ArrowUp"&&!S.items.length){e.preventDefault();cmdHistory(-1);}
      else if(e.key==="ArrowDown"&&!S.items.length){e.preventDefault();cmdHistory(1);}
      else if(e.key==="Tab"){e.preventDefault();cycleView();}
    });
    inp.addEventListener("focus",onPromptFocus);
    inp.addEventListener("blur",onPromptBlur);
    inp.addEventListener("input",function(){if(inp.value.indexOf(":")===0){/* could show command hints */}});
    document.addEventListener("keydown",onKey);
    $("help-close").addEventListener("click",function(){$("help-overlay").classList.add("hidden");});
    $("help-overlay").addEventListener("click",function(e){if(e.target===$("help-overlay"))$("help-overlay").classList.add("hidden");});
    // Genre modal listeners
    $("genre-close").addEventListener("click",closeGenreModal);
    $("genre-modal").addEventListener("click",function(e){if(e.target===$("genre-modal"))closeGenreModal();});
    $("genre-search").addEventListener("input",function(){
      var kw=this.value.trim().toLowerCase();
      var curSrc=getActiveSource();
      loadGenres(curSrc).then(function(list){
        var filtered=kw?list.filter(function(g){
          return (g.title+" "+g.slug).toLowerCase().indexOf(kw)>=0;
        }):list;
        renderGenreList(filtered, curSrc);
      });
    });
    $("clear-hist").addEventListener("click",async function(){
      try{await fetch("/api/history",{method:"DELETE"});}catch(e){}
      App.renderContinue();log("riwayat dihapus","ok");
    });
    var btnClearSearch = $("clear-search-hist");
    if(btnClearSearch){
      btnClearSearch.addEventListener("click", function(){
        clearAllRecents();
      });
    }
    document.querySelectorAll("#schedule-days-bar button").forEach(function(btn){
      btn.addEventListener("click", function(){
        var d = btn.getAttribute("data-day");
        S.scheduleDay = d;
        updateScheduleChips();
        setView("terbaru");
      });
    });
    $("sb-view").textContent="view: "+S.view;
    renderRecents();
  }

  return {boot:boot,log:log,clearLog:clearLog,setView:setView,loadView:loadView,goToPage:goToPage,pagePrev:pagePrev,pageNext:pageNext,moveSel:moveSel,renderSel:renderSel,openSelected:openSelected,startSearch:startSearch,doSearch:doSearch,renderResults:renderResults,renderPager:renderPager,renderRecents:renderRecents,removeRecent:removeRecent,clearAllRecents:clearAllRecents,cmdUsage:cmdUsage,openGenreModal:openGenreModal,openSourceHome:openSourceHome,view:function(){return S.view;},state:function(){return S;}};
})();