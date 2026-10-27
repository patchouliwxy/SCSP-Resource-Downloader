"use strict";
const $=id=>document.getElementById(id);
const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const format=n=>new Intl.NumberFormat("zh-CN").format(n||0);
const bytes=n=>n<1024?`${n} B`:n<1048576?`${(n/1024).toFixed(1)} KiB`:`${(n/1048576).toFixed(2)} MiB`;
const icons={head:"♙",hair:"〰",dress:"◇",accessory:"✧",dance:"♫",animation:"▷",expression:"☺",audio:"♬",texture:"▧",other:"▱"};
const state={view:"library",category:"",page:1,total:0,meta:null,rows:new Map(),selected:new Map(),song:null,jobs:[],plan:null,sceneFormat:"unity",requestSequence:0};
try{const saved=JSON.parse(localStorage.getItem("scsp-selection")||"{}");state.selected=new Map((saved.items||[]).map(r=>[r.id,r]));state.song=saved.song||null;}catch{}
const finishedStatuses=["completed","failed","canceled","interrupted"];
let cleanupIds=[];
let toastTimer;
function toast(message){$("toast").textContent=message;$("toast").classList.add("visible");clearTimeout(toastTimer);toastTimer=setTimeout(()=>$("toast").classList.remove("visible"),4000);}
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-SCSP-Client":"1"},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw new Error(result.error||"请求失败");return result;}
let songOptions={expression:true,camera:true,timeline:true,mouth_ids:null},songOptionCode=null,includeRaw=false;
function selection(){if(songOptionCode!==state.song?.code){songOptionCode=state.song?.code;songOptions={expression:true,camera:true,timeline:true,mouth_ids:null};}return {song_options:songOptions,include_raw:includeRaw,convert_generic_humanoid:true,ids:[...state.selected.keys()],song_code:state.song?.code||"",slots:state.song?.slots||[],scene_export_format:state.sceneFormat};}
function save(){localStorage.setItem("scsp-selection",JSON.stringify({items:[...state.selected.values()],song:state.song}));}
function characterLabel(code){return state.meta?.character_names?.[code]||"角色编号 "+code;}
function defaultPosition(song,slot){return (song.default_lineup||[]).find(m=>m.position===slot);}
function categoryName(key){return state.meta?.categories.find(c=>c.id===key)?.label||"资源";}
function renderBasket(){
 const count=state.selected.size+(state.song?1:0);$("basket-count").textContent=count;$("selection-count").textContent=count+" 项";$("plan-button").disabled=!count;$("clear-basket").hidden=!count;$("mobile-selection").hidden=!count;$("mobile-selection-count").textContent=`已选择 ${count} 项`;
 const items=[...state.selected.values()].map(r=>`<div class="basket-item"><div><strong>${esc(r.display_name||r.name)}</strong><small>${esc(categoryName(r.category))} · ${bytes(r.size)}</small></div><button data-remove="${esc(r.id)}" aria-label="移除 ${esc(r.name)}">×</button></div>`);
 if(state.song)items.unshift(`<div class="basket-item"><div><strong>${esc(state.song.title||state.song.code)} · 主舞蹈文件族</strong><small>${state.song.slots.length?"站位 "+state.song.slots.join("、"):"单文件 / 未编号"} · 包含已命名配套数据</small></div><button data-remove-song aria-label="移除当前歌曲">×</button></div>`);
 $("basket-items").innerHTML=count?items.join(""):`<div class="basket-empty">尚未选择资源<br>点击 + 加入下载清单</div>`;
 $("basket-items").querySelectorAll("[data-remove]").forEach(b=>b.onclick=()=>{state.selected.delete(b.dataset.remove);save();renderBasket();syncCards();});
 $("basket-items").querySelector("[data-remove-song]")?.addEventListener("click",()=>{state.song=null;save();renderBasket();});
}
function syncCards(){document.querySelectorAll(".resource-card").forEach(card=>{const selected=state.selected.has(card.dataset.id);card.classList.toggle("selected",selected);const b=card.querySelector(".select-card");b.textContent=selected?"✓":"+";b.setAttribute("aria-pressed",String(selected));});}
function toggleResource(row){if(state.selected.has(row.id))state.selected.delete(row.id);else{if(state.selected.size>=100){toast("最多选择100个资源；歌曲配套会自动加入计划");return;}state.selected.set(row.id,row);}save();renderBasket();syncCards();}
function resourceCard(r){const color=(r.scope==="audio"||["dance","animation"].includes(r.category))?"blue-cover":["dress","accessory","expression"].includes(r.category)?"rose-cover":"";const chosen=state.selected.has(r.id);return `<article class="resource-card ${chosen?"selected":""}" data-id="${esc(r.id)}"><div class="resource-cover ${color}"><span class="cover-label">${esc(r.type.toUpperCase())}</span><button class="select-card" aria-label="选择 ${esc(r.name)}" aria-pressed="${chosen}">${chosen?"✓":"+"}</button></div><div class="card-body"><h3 title="${esc(r.name)}">${esc(r.display_name||r.name)}</h3>${r.display_name?`<small class="resource-code">${esc(r.name)}</small>`:""}${r.related_song_titles?.length?`<small class="resource-code">使用曲：${r.related_song_titles.slice(0,3).map(esc).join("、")}${r.related_song_titles.length>3?" 等 "+r.related_song_titles.length+" 首":""}</small>`:""}<div class="card-tags"><span class="tag">${esc(categoryName(r.category))}</span>${r.character?`<span class="tag">${esc(r.character_name||characterLabel(r.character))} · ${esc(r.character)}</span>`:""}</div>${r.category==="audio_story"?`<div class="card-tags">${(r.audio_characters||[]).map(c=>`<span class="tag">${esc(c.name)} · ${c.cue_count} Cue</span>`).join("")}${r.audio_indexed?`<span class="tag">${r.audio_cue_count} 个 Cue</span>`:`<span class="tag">角色索引尚未完成</span>`}</div>`:""}<div class="card-meta"><span>${bytes(r.size)} · ${r.dependencies} 个依赖</span>${["head","hair","dress","accessory"].includes(r.category)?`<button class="preview-model-button">3D 预览</button>`:""}${["png","jpg","jpeg"].includes(r.type)?`<button class="preview-image-button">图片预览</button>`:""}${r.motion_preview?`<button class="preview-motion-button">动作预览</button>`:""}${["acb","awb"].includes(r.type)?`<button class="listen-resource-button">试听</button>`:""}<button class="detail-button">详情 ↗</button></div></div></article>`;}
async function showDetail(id){
 try{const e=await api("/api/resource?id="+encodeURIComponent(id));$("detail-body").innerHTML=`<p class="detail-name">${esc(e.display_name||e.name)}</p>${e.display_name?`<div class="source-row"><span>原始文件名</span><strong>${esc(e.name)}</strong></div>`:""}${e.scene_title_basis?`<div class="source-row"><span>名称 / 关联依据</span><strong>${esc(e.scene_title_basis)}</strong></div>`:""}<div class="source-row"><span>完整资源 ID</span><strong>${esc(e.id)}</strong></div><div class="source-row"><span>类别 / 类型</span><strong>${esc(categoryName(e.category))} / ${esc(e.type)}</strong></div><div class="source-row"><span>原始下载体积</span><strong>${bytes(e.size)}</strong></div><div class="source-row"><span>角色编号</span><strong>${e.character?esc(e.character)+"（按名称推断）":e.category==="audio_story"?"见下方包内 Cue 角色标签":"未识别"}</strong></div><div class="source-row"><span>分类依据</span><strong>${esc(e.category_basis||"未提供")}</strong></div>${e.scope==="scene"?`<p class="source-note">选择 .unity 场景后，可在下载计划中选择 Unity 工程或单个 FBX。每个场景对应一个 FBX，包含可导出的几何、层级、基础材质与贴图。游戏脚本与 Shader 源码未恢复，显示效果和动态演出需要适配；版本要求见包内说明。场景模型部件单独选择时不生成整套场景。</p>`:""}${e.category==="audio_story"?`<div id="cue-index-detail" data-id="${esc(e.id)}">读取包内 Cue 索引…</div>`:""}<details open><summary>目录声明的依赖 · ${e.dependencies.length}</summary><ul>${e.dependencies.map(d=>`<li>${esc(d)}</li>`).join("")||"<li>没有声明依赖</li>"}</ul></details><details><summary>包内地址 · ${e.contents.length}</summary><ul>${e.contents.map(c=>`<li>${esc(c)}</li>`).join("")||"<li>索引未提供包内地址</li>"}</ul></details><p class="source-note">下载计划会递归解析依赖。这里展示的是目录记录；依赖是否能在当前索引中找到，请以计划的缺项结果为准。</p>`;$("detail-dialog").showModal();if(e.category==="audio_story")loadCueDetail(e.id);}catch(e){toast(e.message);}
}
const libraryViews=["library","motions","scenes","audios"];
const viewScope=()=>({motions:"motion",scenes:"scene",audios:"audio"}[state.view]||"");
function renderCategories(){
 if(!state.meta)return;
 const visible=state.meta.categories.filter(c=>!viewScope()||c.scope===viewScope());
 const groups={model:"角色模型",motion:"动作与演出",scene:"场景与背景",audio:"音频",other:"其他资源"};
 const button=c=>`<button class="nav-button category-button ${state.category===c.id?"active":""}" data-category="${esc(c.id)}">${esc(c.label)}<span class="category-count">${format(c.count)}</span></button>`;
 $("categories").innerHTML=viewScope()?visible.map(button).join(""):Object.entries(groups).map(([scope,label])=>`<details class="category-group" ${scope==="model"||visible.some(c=>c.scope===scope&&c.id===state.category)?"open":""}><summary>${label}</summary>${visible.filter(c=>c.scope===scope).map(button).join("")}</details>`).join("");
 $("category-filter").innerHTML=`<option value="">所有分类</option>`+visible.map(c=>`<option value="${esc(c.id)}">${esc(c.label)} · ${format(c.count)}</option>`).join("");
 $("category-filter").value=state.category;
 document.querySelectorAll("[data-category]").forEach(b=>b.onclick=()=>{state.category=b.dataset.category;$("search").value="";$("type").value="";setView(libraryViews.includes(state.view)?state.view:"library");});
}
async function loadResources(){
 const sequence=++state.requestSequence;const params=new URLSearchParams({q:$("search").value,category:state.category,scope:viewScope(),type:$("type").value,character:$("character").value,page:state.page,sort:$("sort").value});
 $("results").setAttribute("aria-busy","true");
 try{const data=await api("/api/resources?"+params);if(sequence!==state.requestSequence||!libraryViews.includes(state.view))return;state.total=data.total;state.rows=new Map(data.items.map(r=>[r.id,r]));$("results").className="resource-grid";$("results").innerHTML=data.items.map(resourceCard).join("")||`<div class="empty-state">没有找到匹配资源<br><small>尝试资源名片段、歌曲代码，或清除类型与角色筛选。</small></div>`;$("result-count").textContent=format(data.total)+" 项";$("result-title").textContent=state.category?categoryName(state.category):({motions:"全部动作与演出",scenes:"全部场景与背景",audios:"全部音频资源"}[state.view]||"全部资源");$("pagination").hidden=data.total<=30;$("page-label").textContent=`${state.page} / ${Math.max(1,Math.ceil(data.total/30))}`;$("prev-page").disabled=state.page<=1;$("next-page").disabled=state.page*30>=data.total;document.querySelectorAll(".resource-card").forEach(card=>{card.querySelector(".select-card").onclick=()=>toggleResource(state.rows.get(card.dataset.id));card.querySelector(".detail-button").onclick=()=>showDetail(card.dataset.id);card.querySelector(".preview-image-button")?.addEventListener("click",()=>openImagePreview(state.rows.get(card.dataset.id)));card.querySelector(".preview-motion-button")?.addEventListener("click",()=>openMotionPreview(state.rows.get(card.dataset.id)));card.querySelector(".listen-resource-button")?.addEventListener("click",()=>openAudioListen(state.rows.get(card.dataset.id)));card.querySelector(".preview-model-button")?.addEventListener("click",()=>openModelPreview(state.rows.get(card.dataset.id)));});}catch(e){if(sequence===state.requestSequence){$("results").innerHTML=`<div class="empty-state">${esc(e.message)}</div>`;toast(e.message);}}finally{$("results").setAttribute("aria-busy","false");}
}
async function loadSongs(){
 const sequence=++state.requestSequence;
 try{const songs=await api("/api/songs?q="+encodeURIComponent($("search").value));if(sequence!==state.requestSequence||state.view!=="songs")return;$("result-title").textContent="歌曲身体动作文件族";$("result-count").textContent=songs.length+" 个文件族";$("results").className="resource-grid";$("results").innerHTML=songs.map(s=>`<article class="song-card" data-code="${esc(s.code)}"><h3>${esc(s.title||s.code)}</h3><p>${s.artist?esc(s.artist)+"<br>":""}<span>${esc(s.code)}</span><br>${s.mode!=="numbered"&&s.default_lineup?.length>1?"多人共享动作":s.mode==="single"?"单文件 · 无站位编号":s.slots.length+" 个可选站位"} · 内部歌曲代码<br>${s.formats.includes("body_asset")?"含 _body.asset 原始身体动作数据":"AnimationClip 文件族"}</p>${!s.slots.length&&s.default_lineup?.length?`<p class="default-lineup">默认编队：${s.default_lineup.map(m=>`${m.position} · ${esc(m.name)}（${String(m.character_id).padStart(2,"0")}）`).join(" / ")}</p>`:""}<div class="slot-list">${s.slots.map(slot=>`<label><input type="checkbox" value="${slot}" checked aria-label="${esc(s.code)} 第${slot}站位">${slot}号位${defaultPosition(s,slot)?` · ${esc(defaultPosition(s,slot).name)}（默认）`:""}</label>`).join("")}</div><div class="song-actions"><button data-dance>加入动作 →</button><button data-listen ${s.audio?.length?"":"disabled"}>试听音乐 ▷</button><button data-music ${s.audio?.length?"":"disabled"}>下载音乐 ♬</button></div>${s.audio?.length?`<select class="song-audio" aria-label="${esc(s.title||s.code)} 音乐版本">${s.audio.map(a=>`<option value="${esc(a.id)}">${esc(a.name.toLowerCase()===s.code+".acb"?"主版本 · "+a.name:a.name)} · ${bytes(a.size)}</option>`).join("")}</select>`:`<small>未找到对应音乐包</small>`}</article>`).join("")||`<div class="empty-state">没有找到该歌曲的主舞蹈文件族<br><small>这里只列出名称匹配的主舞蹈，其他演出片段可在资源库搜索。</small></div>`;document.querySelectorAll(".song-card").forEach(card=>card.querySelector("[data-dance]").onclick=()=>{const slots=[...card.querySelectorAll("input:checked")].map(i=>Number(i.value));if(!slots.length&&card.querySelectorAll("input").length){toast("至少选择一个站位");return;}state.song={code:card.dataset.code,slots,title:songs.find(s=>s.code===card.dataset.code)?.title||""};save();renderBasket();toast("已选择 "+card.dataset.code+(slots.length?" 的 "+slots.length+" 个站位":" 的单文件动作数据"));});document.querySelectorAll(".song-card [data-listen]").forEach(button=>button.onclick=()=>{const card=button.closest(".song-card");const song=songs.find(s=>s.code===card.dataset.code);const audio=song.audio.find(a=>a.id===card.querySelector(".song-audio").value);if(audio)openAudioListen(audio);});document.querySelectorAll(".song-card [data-music]").forEach(button=>button.onclick=()=>{const card=button.closest(".song-card");const song=songs.find(s=>s.code===card.dataset.code);const audio=song.audio.find(a=>a.id===card.querySelector(".song-audio").value);if(!audio)return;if(!state.selected.has(audio.id)&&state.selected.size>=100){toast("最多选择100个资源");return;}state.selected.set(audio.id,audio);save();renderBasket();showPlan();});}catch(e){toast(e.message);}
}
const statuses={queued:"等待下载",running:"正在下载",exporting:"正在导出资源",packaging:"正在打包",canceling:"正在停止",canceled:"已取消",completed:"下载完成",failed:"下载失败",interrupted:"上次未完成"};
function renderJobs(){
 $("result-title").textContent="下载任务";$("result-count").textContent=state.jobs.length+" 个任务";$("results").className="job-list";$("job-cleanup-tools").hidden=false;
 $("clear-finished-jobs").disabled=!state.jobs.some(j=>finishedStatuses.includes(j.status));
 $("job-storage-summary").textContent="任务文件占用约 "+bytes(state.jobs.reduce((sum,j)=>sum+(j.stored_bytes||0),0))+"（不含共享缓存）";
 $("results").innerHTML=state.jobs.map(j=>{const progress=jobProgress(j);return `<article class="job-card"><div class="job-head"><h3>任务 ${esc(j.id)}</h3><span class="job-status">${statuses[j.status]||esc(j.status)}</span></div>${jobPhaseRow(j)}<div class="progress-track"><div class="progress-bar" style="width:${progress}%"></div></div><p>${j.completed_files} / ${j.total_files} 个文件 · ${bytes(j.completed_bytes)} / ${bytes(j.total_bytes)}${j.current?"<br>"+esc(j.current):""}</p>${jobTransferStats(j)}${j.missing_count?`<p class="warning-text">保留 ${j.missing_count} 项依赖缺项，下载完成不代表依赖完整。</p>`:""}${j.export_warnings?.length?`<p class="warning-text">${j.export_warnings.map(esc).join("<br>")}</p>`:""}${j.error?`<p class="error-text">${esc(j.error)}</p>`:""}${j.scene_warnings?.length?`<p class="warning-text">${j.scene_warnings.map(esc).join("<br>")}</p>`:""}<p>${j.model_only?"模型包仅含 FBX 和贴图 · ":""}${j.model_count?"已导出 "+j.model_count+" 个 FBX · ":""}${j.scene_count?"已导出 "+j.scene_count+(j.scene_export_format==="fbx"?" 个场景 FBX · ":" 个 Unity 场景 · "):""}${j.animation_count?(j.scene_count?"附带场景动画 ":"已导出 ")+j.animation_count+" 个 anim · ":""}${j.audio_count?"已转 "+j.audio_count+" 个 WAV · ":""}${j.mouth_count?"已导出 "+j.mouth_count+" 份口型 · ":""}保存位置：${esc(j.output_path)}${typeof j.stored_bytes==="number"?"<br>任务文件占用："+bytes(j.stored_bytes):""}</p>${j.scene_count?`<p class="source-note">${j.scene_export_format==="fbx"?"每个场景一个 FBX，贴图在同目录；保留几何与层级，不包含动态演出和游戏 Shader。":"解压 ZIP 后在 Unity Hub 添加 scene-project，打开 "+(j.scene_files||[]).map(esc).join("、")+"。游戏脚本与 Shader 需适配。"}</p>`:""}<div class="job-actions">${j.status==="completed"?`<a class="download-archive" href="/api/jobs/${j.id}/archive">保存 ZIP ↓</a>${(j.model_files||[]).slice(0,3).map((f,i)=>`<a href="/api/jobs/${j.id}/model/${i}">FBX · ${esc(f.split("/").pop())} ↓</a>`).join("")}${(j.mouth_files||[]).slice(0,3).map(f=>`<a href="/api/jobs/${j.id}/mouth/${encodeURIComponent(f.split("/").pop())}">口型JSON · ${esc(f.split("/").pop())} ↓</a>`).join("")}${(j.audio_files||[]).slice(0,3).map(f=>`<a href="/api/jobs/${j.id}/audio/${encodeURIComponent(f.split("/").pop())}">WAV · ${esc((j.audio_tracks||[]).find(t=>t.file===f)?.track_name||f.split("/").pop())} ↓</a>`).join("")}${(j.scene_count?[]:(j.animation_files||[])).slice(0,3).map(f=>`<a href="/api/jobs/${j.id}/animation/${encodeURIComponent(f.split("/").pop())}">独立anim · ${esc(f.split("/").pop())} ↓</a>`).join("")}`:""}<a href="/api/jobs/${j.id}/manifest">完整资源与缺项清单</a>${["queued","running"].includes(j.status)?`<button data-cancel="${j.id}">取消任务</button>`:""}${["failed","canceled","interrupted"].includes(j.status)?`<button data-retry-job="${j.id}" data-retry-mode="resume">继续任务</button>`:""}${["failed","interrupted","completed"].includes(j.status)&&!j.model_only&&j.completed_files===j.total_files?`<button data-retry-job="${j.id}" data-retry-mode="export">仅重新导出</button>`:""}${finishedStatuses.includes(j.status)?`<button class="delete-job-button" data-remove-job="${j.id}">删除任务</button>`:""}</div></article>`;}).join("")||`<div class="empty-state">还没有下载任务<br><small>从资源库或歌曲主舞蹈加入清单，查看计划后即可开始。</small></div>`;
 document.querySelectorAll("[data-retry-job]").forEach(b=>b.onclick=async()=>{b.disabled=true;try{await api(`/api/jobs/${b.dataset.retryJob}/retry`,{mode:b.dataset.retryMode});toast(b.dataset.retryMode==="export"?"重新导出已排队，旧产物会保留":"任务已继续，正在校验已有文件");await pollJobs();}catch(e){toast(e.message);b.disabled=false;}});
 document.querySelectorAll("[data-remove-job]").forEach(b=>b.onclick=()=>openJobCleanup([b.dataset.removeJob]));
 document.querySelectorAll("[data-cancel]").forEach(b=>b.onclick=async()=>{try{await api(`/api/jobs/${b.dataset.cancel}/cancel`,{});await pollJobs();}catch(e){toast(e.message);}});
}
async function pollJobs(){try{state.jobs=await api("/api/jobs");$("job-nav-count").textContent=state.jobs.length;if(state.view==="jobs")renderJobs();}catch{}}
function setView(view){
 state.view=view;state.requestSequence++;state.page=1;
 const library=libraryViews.includes(view);
 const title={library:"资源库",motions:"动作库",scenes:"场景库",audios:"音频库",songs:"歌曲动作",jobs:"下载任务"}[view];
 document.querySelectorAll("[data-view]").forEach(b=>b.classList.toggle("active",b.dataset.view===view));
 $("breadcrumb").textContent=title;$("page-title").textContent=title;
 $("audio-role-tools").hidden=view!=="audios";if(view==="audios")pollAudioRoles();$("job-cleanup-tools").hidden=view!=="jobs";$("resource-tools").hidden=view==="jobs";
 document.querySelector(".filters").hidden=!library;$("quick-search").hidden=view!=="library";$("pagination").hidden=!library;
 $("categories").hidden=!library;document.querySelector(".category-heading").hidden=!library;
 $("result-hint").textContent=view==="songs"?"默认角色来自歌曲编队，站位编号不是角色编号":view==="audios"?"按资源包统计，非音轨数量；用途按命名分类":view==="scenes"?"选择 Unity 工程或单个 FBX；支持按官方曲名搜索":view==="motions"?"用途按命名规则分类，详情可查看依据":"选择资源后可查看依赖计划";
 renderCategories();
 if(library)loadResources();else if(view==="songs")loadSongs();else pollJobs();
}

async function showPlan(){
 $("plan-button").disabled=true;$("plan-button").textContent="正在解析依赖…";
 try{state.plan=await api("/api/plan",selection());const p=state.plan;$("song-export-options").hidden=!state.song;for(const key of ["expression","camera","timeline"])$("song-"+key).checked=songOptions[key];$("include-raw").checked=includeRaw;$("song-mouth-options").innerHTML=(p.song_selection?.mouth_candidates||[]).map(m=>`<label style="display:block"><input type="checkbox" data-mouth-id="${esc(m.id)}" ${(songOptions.mouth_ids===null||songOptions.mouth_ids.includes(m.id))?"checked":""}> ${esc(m.name)}</label>`).join("")||"此歌曲没有口型候选";$("plan-body").innerHTML=`<div class="plan-numbers"><div><span>含递归依赖</span><strong>${format(p.unique_files)} 个文件</strong></div><div><span>原始下载体积</span><strong>${bytes(p.total_bytes)}</strong></div><div><span>依赖缺项</span><strong>${p.missing_count} 项</strong></div></div><div class="plan-notice ${p.dependency_complete?"plan-ok":""}">${p.dependency_complete?"当前索引内的声明依赖已解析。":"有依赖或歌曲配套缺项。可以先检查报告，或明确允许带缺项下载。"}${p.model_only?"模型 ZIP 仅包含编号文件夹中的 FBX 和贴图；导出成功后清理临时原始包，不导出附带 anim。":(p.scene_export_requested?`<span id="scene-export-description">${sceneExportNote(p.scene_export_format)}</span>`:"动作、口型和音乐按支持格式导出；歌曲表情、镜头、编队和时间线保留。")}${includeRaw?"附带全部原始包。":"成功后清理中间工程与临时原始包，保留交付数据和共用缓存。"}生成体积可能大于下载体积。</div><details ${p.missing_count?"open":""}><summary>缺项报告 · ${p.missing_count}${p.missing_count>100?"（展示前100项）":""}</summary><ul>${p.unresolved_dependencies.map(d=>`<li>${esc(d)}</li>`).join("")||"<li>未发现声明依赖缺项</li>"}</ul></details><details><summary>资源计划 · ${p.entry_count} 项${p.entry_count>100?"（展示前100项）":""}</summary><ul>${p.items.map(e=>`<li>${esc(e.name)} · ${bytes(e.size)}</li>`).join("")}</ul></details>`;$("scene-export-options").hidden=!p.scene_export_requested;$("scene-export-format").value=state.sceneFormat;$("allow-unresolved").checked=false;$("allow-unresolved").closest("label").hidden=!p.missing_count;$("download-error").textContent="";$("download-button").disabled=!!p.missing_count;$("plan-dialog").showModal();}catch(e){toast(e.message);}finally{$("plan-button").innerHTML="查看下载计划 <span>→</span>";$("plan-button").disabled=!(state.selected.size||state.song);}
}
async function startDownload(){
 $("download-button").disabled=true;$("download-button").textContent="正在提交…";
 const submittedItems=new Map(state.selected),submittedSong=state.song;
 try{await api("/api/download",{...selection(),allow_unresolved:$("allow-unresolved").checked,max_total_mb:Number($("download-limit").value)});
  for(const [id,item] of submittedItems)if(state.selected.get(id)===item)state.selected.delete(id);
  if(state.song===submittedSong)state.song=null;
  try{save();}catch{toast("任务已提交，但浏览器无法保存清单状态");}
  renderBasket();syncCards();$("plan-dialog").close();setView("jobs");toast("下载任务已加入队列，已清空本次提交的选择");}catch(e){$("download-error").textContent=e.message;}finally{$("download-button").textContent="开始下载 ↓";$("download-button").disabled=!!state.plan?.missing_count&&!$("allow-unresolved").checked;}
}
function showSource(){const m=state.meta;if(!m)return;const fields=[["索引来源",m.source_kind==="public_snapshot"?"公开资源快照":"指定版本目录"],["资源版本",m.resource_version],["客户端版本",m.game_version],["名称源客户端版本",m.source_game_version||"—"],["名称源资源版本",m.source_resource_version||"—"],["已映射 / 快照文件",`${format(m.mapped_files??m.entry_count)} / ${format(m.snapshot_files??m.entry_count)}`],["未映射文件",format(m.unmapped_files??0)],["官方实时最新版本",m.official_live_latest_verified?"已验证":"未验证"]];$("source-body").innerHTML=fields.map(([key,value])=>`<div class="source-row"><span>${key}</span><strong>${esc(value)}</strong></div>`).join("")+`<p class="source-note">名称与分类基于当前本地索引。角色编号按文件命名推断，尚未提供完整中文角色名及歌曲名映射。未映射文件暂无法按名称浏览；本页面不会把旧名称目录称为当前完整官方目录。</p>`;$("source-dialog").showModal();}
document.querySelectorAll("[data-view]").forEach(b=>b.onclick=()=>{state.category="";$("category-filter").value="";document.querySelectorAll(".category-button").forEach(c=>c.classList.remove("active"));$("search").value="";$("type").value="";$("character").value="";setView(b.dataset.view);});
document.querySelectorAll("[data-close]").forEach(b=>b.onclick=()=>$(b.dataset.close).close());
document.querySelectorAll("dialog").forEach(d=>d.addEventListener("click",e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}}));
let debounce;$("search").oninput=()=>{clearTimeout(debounce);debounce=setTimeout(()=>{state.page=1;state.view==="songs"?loadSongs():loadResources();},250);};
["character","type","sort"].forEach(id=>$(id).onchange=()=>{state.page=1;loadResources();});
document.querySelectorAll("[data-search]").forEach(b=>b.onclick=()=>{state.category="";$("category-filter").value="";$("type").value="";$("character").value="";$("search").value=b.dataset.search;document.querySelectorAll(".category-button").forEach(c=>c.classList.remove("active"));setView("library");});
$("prev-page").onclick=()=>{state.page--;loadResources();};$("next-page").onclick=()=>{state.page++;loadResources();};
$("clear-basket").onclick=()=>{state.selected.clear();state.song=null;save();renderBasket();syncCards();};
$("plan-button").onclick=showPlan;$("download-button").onclick=startDownload;$("allow-unresolved").onchange=()=>{$("download-button").disabled=!!state.plan?.missing_count&&!$("allow-unresolved").checked;};
$("mobile-plan-button").onclick=showPlan;
$("category-filter").onchange=()=>{state.category=$("category-filter").value;state.page=1;document.querySelectorAll(".category-button").forEach(b=>b.classList.toggle("active",b.dataset.category===state.category));loadResources();};
$("source-button").onclick=showSource;$("coverage-source").onclick=showSource;
$("refresh-button").onclick=()=>{if(state.view==="jobs")pollJobs();else if(state.view==="songs")loadSongs();else loadResources();};
document.addEventListener("keydown",e=>{if(e.key==="/"&&!document.querySelector("dialog[open]")&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)){e.preventDefault();$("search").focus();}});
async function init(){renderBasket();try{state.meta=await api("/api/meta");const m=state.meta;$("named-count").textContent=format(m.mapped_files??m.entry_count);$("song-count").textContent=m.song_count;$("song-nav-count").textContent=m.song_count;$("unmapped-count").textContent=format(m.unmapped_files??0);$("snapshot-pill").textContent=(m.source_kind==="public_snapshot"?"公开快照 ":"资源版本 ")+m.resource_version.split("@")[0];$("coverage-note").textContent=m.source_kind==="public_snapshot"?`已命名 ${format(m.mapped_files)} / ${format(m.snapshot_files)} 个文件。名称索引不完整，公开快照不代表官方实时最新版本。`:"当前目录由游戏内完整版本参数直接解析官方CDN取得；不代表已自动检查后续更新。";$("motion-nav-count").textContent=format(m.scope_counts?.motion);$("scene-nav-count").textContent=format(m.scope_counts?.scene);$("audio-nav-count").textContent=format(m.scope_counts?.audio);renderCategories();$("character").insertAdjacentHTML("beforeend",m.characters.map(c=>`<option value="${esc(c)}">${esc(characterLabel(c))} · ${esc(c)}</option>`).join(""));$("type").insertAdjacentHTML("beforeend",m.types.map(t=>`<option value="${esc(t)}">.${esc(t)}</option>`).join(""));await Promise.all([loadResources(),pollJobs()]);const initialView=location.hash.slice(1);if(["songs","jobs","motions","scenes","audios"].includes(initialView))setView(initialView);setInterval(pollJobs,2500);setInterval(pollAudioRoles,5000);}catch(e){$("results").innerHTML=`<div class="empty-state">无法加载资源索引<br>${esc(e.message)}</div>`;toast(e.message);}}
init();

function cleanupMode(){
 const removeFiles=$("delete-task-files").checked;
 $("confirm-job-cleanup").textContent=removeFiles?"删除任务及文件":"只清除任务记录";
 $("job-cleanup-note").textContent=removeFiles?"将删除这些任务的下载目录、ZIP、动画/WAV/口型及导出临时文件。已复制到Unity或其他位置的文件和共享缓存保留。":"只从任务列表移除记录，不释放文件占用；下载目录和ZIP保留，需要时可从磁盘自行取用。";
}
function openJobCleanup(ids){
 cleanupIds=ids.slice(0,1000);const selected=state.jobs.filter(j=>cleanupIds.includes(j.id));
 $("job-cleanup-summary").textContent=`选中 ${selected.length} 个已结束任务，任务文件约 ${bytes(selected.reduce((sum,j)=>sum+(j.stored_bytes||0),0))}。`;
 $("delete-task-files").checked=true;$("job-cleanup-error").textContent="";cleanupMode();$("job-cleanup-dialog").showModal();
}
$("clear-finished-jobs").onclick=()=>openJobCleanup(state.jobs.filter(j=>finishedStatuses.includes(j.status)).map(j=>j.id));
$("delete-task-files").onchange=cleanupMode;
$("confirm-job-cleanup").onclick=async()=>{
 const button=$("confirm-job-cleanup");button.disabled=true;
 try{const result=await api("/api/jobs/clear",{ids:cleanupIds,delete_files:$("delete-task-files").checked});await pollJobs();
  if(result.errors.length){$("job-cleanup-error").textContent=result.errors.map(e=>e.id+"："+e.error).join("；");cleanupIds=result.errors.map(e=>e.id);}
  else $("job-cleanup-dialog").close();
  toast(`已清理 ${result.removed.length} 个任务${result.freed_bytes?"，释放约 "+bytes(result.freed_bytes):""}`);
 }catch(e){$("job-cleanup-error").textContent=e.message;}finally{button.disabled=false;}
};

let previewGeneration=0, modelViewer=null, currentPreviewKey=null;
$("model-preview-dialog").addEventListener("close",()=>{previewGeneration++;modelViewer?.dispose();modelViewer=null;if(currentPreviewKey){releaseTemporary("previews",currentPreviewKey);currentPreviewKey=null;}});
$("reset-preview").onclick=()=>modelViewer?.reset();
async function openModelPreview(row){
 const generation=++previewGeneration;modelViewer?.dispose();modelViewer=null;
 $("model-preview-name").textContent=(row.character_name?row.character_name+" · ":"")+row.name;
 $("model-preview-canvas").replaceChildren();$("model-preview-status").textContent="正在准备模型，首次预览会按需下载依赖…";
 $("model-preview-dialog").showModal();
 try{
  let job=await api("/api/preview",{id:row.id});if(generation!==previewGeneration){releaseTemporary("previews",job.key);return;}currentPreviewKey=job.key;
  while(["queued","running"].includes(job.status)){
   if(generation!==previewGeneration)return;
   $("model-preview-status").textContent=job.status==="queued"?"等待生成预览…":"正在读取网格与贴图、生成预览…";
   await new Promise(resolve=>setTimeout(resolve,800));job=await api("/api/previews/"+job.key);
  }
  if(generation!==previewGeneration)return;
  if(job.status!=="completed")throw new Error(job.error||"预览生成失败");
  const module=await import("/preview.js");if(generation!==previewGeneration)return;
  modelViewer=module.createViewer($("model-preview-canvas"),"/api/previews/"+job.key+"/model.glb");await modelViewer.ready;
  if(generation!==previewGeneration)return;
  $("model-preview-status").textContent=`${job.meshes} 个网格 · ${format(job.vertices)} 个顶点 · ${job.textures} 张贴图 · ${bytes(job.bytes)}${job.missing.length?" · 保留 "+job.missing.length+" 项依赖缺项":""}${job.warnings.length?" · 部分材质使用默认外观":""}`;
 }catch(error){if(generation===previewGeneration){modelViewer?.dispose();modelViewer=null;$("model-preview-status").textContent="无法预览："+error.message;}}
}

function releaseTemporary(kind,key){
 fetch(`/api/${kind}/${key}/release`,{method:"POST",headers:{"Content-Type":"application/json","X-SCSP-Client":"1"},body:"{}",keepalive:true}).catch(()=>{});
}
let listenGeneration=0,currentListenKey=null,listenTracks=[];
$("audio-listen-dialog").addEventListener("close",()=>{
 listenGeneration++;const player=$("listen-player");player.pause();player.removeAttribute("src");player.load();
 if(currentListenKey){releaseTemporary("listens",currentListenKey);currentListenKey=null;}
});
function selectListenTrack(){
 const track=listenTracks.find(t=>t.track===Number($("listen-track").value));if(!track||!currentListenKey)return;
 const player=$("listen-player");player.pause();player.src=`/api/listens/${currentListenKey}/track/${track.track}`;player.load();
 $("audio-listen-status").textContent=`${track.track_name||"Track "+track.track} · ${track.duration.toFixed(2)} 秒 · ${track.sample_rate/1000} kHz · ${track.channels} 声道${track.characters?.length?" · "+track.characters.map(c=>c.name).join(" / "):""}`;
}
$("listen-track").onchange=selectListenTrack;
async function openAudioListen(audio){
 const generation=++listenGeneration;$("audio-listen-name").textContent=audio.name;$("audio-listen-status").textContent="正在按需读取音轨并准备试听…";
 $("listen-track").replaceChildren();$("listen-track").disabled=true;$("audio-listen-dialog").showModal();
 try{let job=await api("/api/listen",{id:audio.id});if(generation!==listenGeneration){releaseTemporary("listens",job.key);return;}currentListenKey=job.key;
  while(["queued","running"].includes(job.status)){if(generation!==listenGeneration)return;await new Promise(resolve=>setTimeout(resolve,700));job=await api("/api/listens/"+job.key);}
  if(generation!==listenGeneration)return;if(job.status!=="completed")throw new Error(job.error||"无法准备音轨");
  listenTracks=job.tracks;
  const roles=new Map(listenTracks.flatMap(t=>(t.characters||[]).map(c=>[c.id,c.name])));
  $("listen-character").innerHTML='<option value="">所有角色</option>'+[...roles].sort().map(([id,name])=>`<option value="${esc(id)}">${esc(name)}</option>`).join("")+(listenTracks.some(t=>!t.characters?.length)?'<option value="?">未识别角色</option>':"");
  const selected=$("character").value;$("listen-character").value=roles.has(selected)?selected:"";
  renderListenTracks();
 }catch(error){if(generation===listenGeneration)$("audio-listen-status").textContent="试听失败："+error.message;}
}
window.addEventListener("pagehide",()=>{if(currentPreviewKey)releaseTemporary("previews",currentPreviewKey);if(currentListenKey)releaseTemporary("listens",currentListenKey);});

let motionGeneration=0,motionViewer=null,currentMotionKey=null;
$("motion-preview-dialog").addEventListener("close",()=>{motionGeneration++;motionViewer?.dispose();motionViewer=null;if(currentMotionKey){releaseTemporary("motions",currentMotionKey);currentMotionKey=null;}});
$("motion-toggle").onclick=()=>motionViewer?.setPlaying($("motion-toggle").dataset.playing!=="true");
$("motion-seek").oninput=()=>motionViewer?.seek(Number($("motion-seek").value));
$("motion-speed").onchange=()=>motionViewer?.setSpeed(Number($("motion-speed").value));
$("motion-loop").onchange=()=>motionViewer?.setLoop($("motion-loop").checked);
$("motion-reset").onclick=()=>motionViewer?.reset();
async function openMotionPreview(row){
 const generation=++motionGeneration;motionViewer?.dispose();motionViewer=null;
 $("motion-preview-name").textContent=row.name;$("motion-preview-canvas").replaceChildren();
 $("motion-preview-status").textContent="正在准备动作，首次会按需读取资源…";
 $("motion-toggle").disabled=true;$("motion-seek").disabled=true;$("motion-toggle").textContent="播放";$("motion-time").textContent="0.00 / — 秒";
 $("motion-preview-dialog").showModal();
 try{
  let job=await api("/api/motion-preview",{id:row.id});if(generation!==motionGeneration){releaseTemporary("motions",job.key);return;}currentMotionKey=job.key;
  while(["queued","running"].includes(job.status)){
   if(generation!==motionGeneration)return;$("motion-preview-status").textContent=job.stage||"正在准备…";
   await new Promise(resolve=>setTimeout(resolve,700));job=await api("/api/motions/"+job.key);
  }
  if(generation!==motionGeneration)return;if(job.status!=="completed")throw new Error(job.error||"动作预览失败");
  const module=await import("/motion-viewer.js");if(generation!==motionGeneration)return;
  motionViewer=module.createMotionViewer($("motion-preview-canvas"),`/api/motions/${job.key}/motion.json`,`/api/motions/${job.key}/motion.bin`,(t,d,playing)=>{
   $("motion-seek").max=d;$("motion-seek").value=t;$("motion-time").textContent=`${t.toFixed(2)} / ${d.toFixed(2)} 秒`;$("motion-toggle").dataset.playing=String(playing);$("motion-toggle").textContent=playing?"暂停":"播放";
  });
  await motionViewer.ready;if(generation!==motionGeneration)return;
  motionViewer.setSpeed(Number($("motion-speed").value));motionViewer.setLoop($("motion-loop").checked);
  $("motion-toggle").disabled=false;$("motion-seek").disabled=false;
  $("motion-preview-status").textContent=`${job.model_name} · ${job.motion.kind==="lip"?"剧情口型（LipA/I/U/E/O，不是身体动作）":job.motion.kind==="generic_humanoid"?"通用骨骼 → Humanoid":"Humanoid"} · ${job.motion.fps} FPS · ${job.motion.boneCount} 根骨骼${job.missing.length?` · 保留 ${job.missing.length} 项依赖缺项`:""}`;
  if(job.motion.download_file){const a=document.createElement('a');a.href=`/api/motions/${job.key}/${job.motion.download_file}`;a.textContent=job.motion.kind==='lip'?' 保存口型 JSON':' 保存转换后的 Humanoid anim';a.download=job.name.replace(/\.anim$/i,'')+(job.motion.kind==='lip'?'_mouth.json':'_humanoid.anim');$('motion-preview-status').append(a);}
 }catch(error){if(generation===motionGeneration){motionViewer?.dispose();motionViewer=null;$("motion-preview-status").textContent="无法预览："+error.message;}}
}
window.addEventListener("pagehide",()=>{if(currentMotionKey)releaseTemporary("motions",currentMotionKey);});

let lastAudioIndexCount=-1;
async function pollAudioRoles(){
 if(state.view!=="audios")return;
 try{const s=await api("/api/audio-index");
  $("audio-role-status").textContent=`剧情 Cue 角色索引 ${format(s.indexed)} / ${format(s.total)} 个包${s.failed?" · 失败 "+s.failed:""}${s.running?" · 正在读取元数据":s.complete?" · 已完成":" · 未完成"}；筛选仅覆盖已索引包`;
  const b=$("audio-role-toggle");b.textContent=s.running?"暂停索引":s.complete?"检查新增资源":"继续 / 重试索引";b.dataset.running=String(s.running);
  if(lastAudioIndexCount!==s.indexed){const initial=lastAudioIndexCount<0;lastAudioIndexCount=s.indexed;if(!initial&&(state.category==="audio_story"||$("character").value))loadResources();}
 }catch(e){$("audio-role-status").textContent="角色索引状态读取失败："+e.message;}
}
$("audio-role-toggle").onclick=async()=>{try{await api("/api/audio-index",{action:$("audio-role-toggle").dataset.running==="true"?"pause":"start"});await pollAudioRoles();}catch(e){toast(e.message);}};
async function loadCueDetail(id){
 try{const record=await api("/api/audio-index/bank?id="+encodeURIComponent(id));const el=$("cue-index-detail");if(!el||el.dataset.id!==id)return;
  if(!record.cues){el.textContent=record.message;return;}
  el.innerHTML=`<details open><summary>包内 Cue 索引 · ${record.cue_count} 项</summary><p>${(record.characters||[]).map(c=>esc(c.name)+" · "+c.cue_count).join(" / ")||"没有识别到已知角色后缀"}${record.unknown_cues?"；未识别角色 "+record.unknown_cues+" 项":""}</p><ul>${record.cues.slice(0,100).map(c=>`<li>Cue #${c.cue_index} · ${esc(c.cue_name)} · ${c.characters?.length?c.characters.map(x=>esc(x.name)).join(" / "):"未识别角色"}</li>`).join("")}</ul><a href="/api/audio-index/bank?id=${encodeURIComponent(id)}" target="_blank" rel="noopener">查看完整 Cue 索引 JSON ↗</a><p class="source-note">角色来自实际 Cue 名称。Cue 可共享音频波形，其编号不是导出 WAV 的顺序号。</p></details>`;
 }catch(e){const el=$("cue-index-detail");if(el&&el.dataset.id===id)el.textContent="Cue 索引读取失败："+e.message;}
}
function renderListenTracks(){
 const role=$("listen-character").value;const tracks=listenTracks.filter(t=>!role||(role==="?"?!t.characters?.length:t.characters?.some(c=>c.id===role)));
 $("listen-track").innerHTML=tracks.map(t=>`<option value="${t.track}">Track ${t.track} · ${esc(t.characters?.map(c=>c.name).join(" / ")||"未识别角色")} · ${esc(t.track_name||"未命名音轨")} · ${t.duration.toFixed(2)} 秒</option>`).join("");
 $("listen-track").disabled=!tracks.length;
 if(tracks.length)selectListenTrack();else{const p=$("listen-player");p.pause();p.removeAttribute("src");p.load();$("audio-listen-status").textContent="此包没有该角色的已识别音轨";}
}
$("listen-character").onchange=renderListenTracks;

function sceneExportNote(value){return value==="fbx"?"每个场景导出一个 FBX 与贴图，保留可解析的层级和几何；不包含游戏脚本、动态演出或原 Shader。仅场景任务的 ZIP 不夹带原始包，原始包在本地保留。":"恢复 Unity scene-project，含场景、网格、材质与贴图；保留原始资源。游戏脚本与 Shader 需适配。";}
$("scene-export-format").onchange=()=>{state.sceneFormat=$("scene-export-format").value;if(state.plan)state.plan.scene_export_format=state.sceneFormat;const description=$("scene-export-description");if(description)description.textContent=sceneExportNote(state.sceneFormat);};

function jobProgress(j){
 if(j.status==="completed")return 100;
 if(j.status==="queued")return 0;
 let ratio=0;
 if(j.phase==="exporting")ratio=(j.phase_completed||0)/(j.phase_total||5);
 else if(j.phase==="packaging")ratio=j.package_total_bytes?(j.packaged_bytes||0)/j.package_total_bytes:(j.phase_completed||0)/(j.phase_total||1);
 else ratio=j.total_bytes?(j.completed_bytes||0)/j.total_bytes:(j.completed_files||0)/(j.total_files||1);
 return Math.min(100,Math.max(0,ratio*100));
}
function jobPhaseRow(j){
 const phase=j.phase||({running:"downloading",exporting:"exporting",packaging:"packaging",completed:"completed"}[j.status])||"queued";
 const order=["downloading","exporting","packaging"];
 const active=phase==="completed"?3:order.indexOf(phase);
 return `<div class="job-phases">${["下载","导出","打包"].map((label,i)=>`<span class="${i<active?"done":i===active?"active":""}">${i<active?"✓ ":""}${label}</span>`).join('<span class="phase-arrow">→</span>')}<small>${esc(j.phase_label||"")}${phase==="exporting"?" · "+(j.phase_completed||0)+"/"+(j.phase_total||5):""}${phase==="packaging"?" · "+bytes(j.packaged_bytes||0)+" / "+bytes(j.package_total_bytes||0):""}</small></div>`;
}
function jobTransferStats(j){
 if(typeof j.reused_files!=="number")return "";
 return `<p class="job-transfer-stats">本地复用 ${format((j.reused_files||0)+(j.cached_files||0))} 个（已下载 ${format(j.reused_files)} · 缓存 ${format(j.cached_files)}） · 本次网络 ${bytes(j.network_bytes||0)}${j.phase==="downloading"&&j.speed_bps?" · 平均 "+bytes(j.speed_bps)+"/s":""} · 自动重试 ${format(j.retry_count)} 次${j.reused_stages?" · 复用导出阶段 "+format(j.reused_stages)+" 项":""}</p>`;
}

async function refreshSongPlan(event){
 songOptions={expression:$("song-expression").checked,camera:$("song-camera").checked,timeline:$("song-timeline").checked,mouth_ids:event?.target?.dataset.mouthId?[...document.querySelectorAll("[data-mouth-id]:checked")].map(i=>i.dataset.mouthId):songOptions.mouth_ids};
 includeRaw=$("include-raw").checked;
 $("plan-dialog").close();await showPlan();
}
["song-expression","song-camera","song-timeline","include-raw"].forEach(id=>$(id).onchange=refreshSongPlan);
$("song-mouth-options").onchange=refreshSongPlan;

$("listen-player").addEventListener("error",async()=>{
 if(!currentListenKey)return;
 const track=Number($("listen-track").value);
 try{const r=await fetch(`/api/listens/${currentListenKey}/track/${track}`);if(!r.ok){const e=await r.json();$("audio-listen-status").textContent="音轨解码失败："+e.error;}else $("audio-listen-status").textContent="浏览器播放失败，请切换音轨或下载 WAV 检查。";}catch(e){$("audio-listen-status").textContent="试听连接失败："+e.message;}
});
