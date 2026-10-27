let imageGeneration=0,currentImageKey=null,imageWidth=0,imageHeight=0;
function imageZoom(percent){
 if(!imageWidth)return;
 const img=$("image-preview-img");img.style.width=Math.round(imageWidth*percent/100)+"px";
 img.style.height="auto";$("image-zoom").value=Math.min(400,Math.max(10,percent));
}
function fitImage(){
 const viewport=$("image-preview-viewport");
 imageZoom(Math.min(100,100*(viewport.clientWidth-24)/imageWidth,100*(viewport.clientHeight-24)/imageHeight));
}
$("image-fit").onclick=fitImage;
$("image-original").onclick=()=>imageZoom(100);
$("image-zoom").oninput=()=>imageZoom(Number($("image-zoom").value));
$("image-background").onchange=()=>$("image-preview-viewport").dataset.background=$("image-background").value;
$("image-preview-dialog").addEventListener("close",()=>{
 imageGeneration++;const img=$("image-preview-img");img.removeAttribute("src");img.hidden=true;
 $("image-save").hidden=true;imageWidth=0;imageHeight=0;
 if(currentImageKey){releaseTemporary("images",currentImageKey);currentImageKey=null;}
});
window.addEventListener("pagehide",()=>{if(currentImageKey)releaseTemporary("images",currentImageKey);});
async function openImagePreview(row){
 const generation=++imageGeneration;
 $("image-preview-name").textContent=row.name;$("image-preview-status").textContent="正在按需读取贴图…";
 $("image-preview-img").hidden=true;$("image-save").hidden=true;$("image-preview-dialog").showModal();
 try{
  let job=await api("/api/image-preview",{id:row.id});
  if(generation!==imageGeneration){releaseTemporary("images",job.key);return;}
  currentImageKey=job.key;
  while(["queued","running"].includes(job.status)){
   await new Promise(resolve=>setTimeout(resolve,500));if(generation!==imageGeneration)return;
   job=await api("/api/images/"+job.key);
  }
  if(generation!==imageGeneration)return;
  if(job.status!=="completed")throw new Error(job.error||"图片解码失败");
  const img=$("image-preview-img"),url=`/api/images/${job.key}/image.png`;
  img.src=url;await img.decode();if(generation!==imageGeneration)return;
  imageWidth=job.width;imageHeight=job.height;img.hidden=false;fitImage();
  $("image-preview-status").textContent=`${job.width} × ${job.height} · ${bytes(job.bytes)} · ${job.alpha?"含透明通道":"不透明图片"}`;
  const save=$("image-save");save.href=url;save.download=row.name.split('/').pop().replace(/\.(jpg|jpeg)$/i,'.png');save.hidden=false;
 }catch(error){if(generation===imageGeneration)$("image-preview-status").textContent="无法预览："+error.message;}
}
