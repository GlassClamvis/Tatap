function apiBase(){
  var s = localStorage.getItem("tatap_server");
  if(s) return s.replace(/\/+$/,"");
  if(location.protocol === "file:" || !location.origin || location.origin === "null"){
    return "http://127.0.0.1:8767";
  }
  return "";
}
async function jget(u){var r=await fetch(apiBase()+u);return r.json();}
async function jpost(u,b){var r=await fetch(apiBase()+u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b||{})});return r.json();}
window.Tatap={
search:function(q,source){return jget("/api/search?q="+encodeURIComponent(q)+(source?"&source="+encodeURIComponent(source):""));},
catalog:function(p,source){return jget("/api/catalog?page="+(p||1)+(source?"&source="+encodeURIComponent(source):""));},
seasonNow:function(p){return jget("/api/seasonal?which=now&page="+(p||1));},
stillAiring:function(p){return jget("/api/seasonal?which=prev&page="+(p||1));},
seasonBy:function(name,year,p){return jget("/api/seasonal?season="+encodeURIComponent(name)+"&year="+(year||0)+"&page="+(p||1));},
upcoming:function(days,day){return jget("/api/upcoming-episodes?days="+(days||7)+"&day="+(day||"today"));},
schedule:function(day){return jget("/api/schedule?day="+(day||"today"));},
filters:function(){return jget("/api/filters");},
browse:function(params,page){
  var qs = "";
  var p = params || {};
  for (var k in p) if (p[k] !== undefined && p[k] !== null && p[k] !== "") qs += "&"+encodeURIComponent(k)+"="+encodeURIComponent(p[k]);
  if (!p.source && window.cur && window.cur.source) {
    qs += "&source="+encodeURIComponent(window.cur.source);
  }
  return jget("/api/browse?page="+(page||1)+qs);
},
episodes:function(slug){return jget("/api/anime/"+encodeURIComponent(slug)+"/episodes");},
relations:function(slug,title){return jget("/api/anime/"+encodeURIComponent(slug)+"/relations?title="+encodeURIComponent(title||""));},
resolve:function(slug,ep,mode,q,source){return jget("/api/stream/resolve?slug="+encodeURIComponent(slug)+"&ep="+ep+"&mode="+(mode||"sub")+"&q="+(q||"best")+(source?"&source="+encodeURIComponent(source):""));},
genres:function(source){
  var src = source || (window.cur && window.cur.source) || "";
  return jget("/api/genres"+(src ? "?source="+encodeURIComponent(src) : ""));
},
health:function(){return jget("/api/health");},
history:function(){return jget("/api/history");},
saveHist:function(b){return jpost("/api/history",b);},
playMPV:function(b){return jpost("/api/play-mpv",b);},
// Settings (termasuk sub_lang).
getSettings:function(){return jget("/api/settings");},
setSetting:function(b){return jpost("/api/settings",b);},
checkUpdate:function(){return jget("/api/update/check");}
};

