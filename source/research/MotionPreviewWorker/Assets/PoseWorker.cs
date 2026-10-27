using System;
using System.IO;
using System.Linq;
using UnityEngine;

[Serializable] public class PoseInput {public string name;public float fps,duration;public int frameCount;public string[] channels;public float[] samples;public bool generic;public string[] paths;}
[Serializable] public class PoseOutput {public int schema=1,frameCount,boneCount;public float fps,duration;public string name,model="chiyoko-preview-v1";public int[] nodes;public string[] ignoredChannels;}
public class PoseWorker : MonoBehaviour {
 public static string Option(string key){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,key);return i>=0&&i+1<a.Length?a[i+1]:null;}
 public static string Normalize(string s){return s.Replace("LeftHand.","Left ").Replace("RightHand.","Right ").Replace('.',' ');}
 void Start(){
  if(Option("--pose-input")==null)return;
  try{
   var input=JsonUtility.FromJson<PoseInput>(File.ReadAllText(Option("--pose-input")));
   if(input.frameCount<1||input.frameCount>18001||input.channels.Length>2048||input.samples.Length!=input.frameCount*input.channels.Length)throw new Exception("Invalid pose dimensions");
   var actor=Instantiate(Resources.Load<GameObject>("PreviewActor"));
   var animator=actor.GetComponent<Animator>();
   if(!animator||!animator.avatar||!animator.avatar.isValid||!animator.avatar.isHuman)throw new Exception("Preview actor has no valid Humanoid Avatar");
   animator.enabled=false;
   var transforms=actor.GetComponentsInChildren<Transform>(true);
   var nodes=Enumerable.Range(0,(int)HumanBodyBones.LastBone).Select(i=>animator.GetBoneTransform((HumanBodyBones)i)).Where(t=>t).Distinct().ToArray();
   var names=HumanTrait.MuscleName.Select(Normalize).ToArray();
   var muscles=input.channels.Select(c=>Array.IndexOf(names,Normalize(c))).ToArray();
   if(!input.generic&&!muscles.Any(i=>i>=0))throw new Exception("No Humanoid muscle channels");
   using(var handler=new HumanPoseHandler(animator.avatar,actor.transform)){
    var pose=new HumanPose();handler.GetHumanPose(ref pose);
    var neutralPosition=pose.bodyPosition;var neutralRotation=pose.bodyRotation;
    var baseline=(float[])pose.muscles.Clone();
    var baselineP=transforms.Select(t=>t.localPosition).ToArray();var baselineQ=transforms.Select(t=>t.localRotation).ToArray();var baselineS=transforms.Select(t=>t.localScale).ToArray();
    var targets=input.generic?input.paths.Select(p=>string.IsNullOrEmpty(p)?actor.transform:actor.transform.Find(p)).ToArray():null;
    if(input.generic&&targets.Any(t=>!t))throw new Exception("Unmapped generic Transform path");
    var baked=input.generic?new PoseInput{name=input.name,fps=input.fps,duration=input.duration,frameCount=input.frameCount,channels=HumanTrait.MuscleName.Concat(new[]{"RootT.x","RootT.y","RootT.z","RootQ.x","RootQ.y","RootQ.z","RootQ.w"}).ToArray(),samples=new float[input.frameCount*(HumanTrait.MuscleName.Length+7)]}:null;
    using(var output=new BinaryWriter(File.Create(Option("--pose-out")+".bin"))){
     for(int frame=0;frame<input.frameCount;frame++){
      Array.Copy(baseline,pose.muscles,baseline.Length);pose.bodyPosition=neutralPosition;pose.bodyRotation=neutralRotation;
      if(input.generic){
       for(int t=0;t<transforms.Length;t++){transforms[t].localPosition=baselineP[t];transforms[t].localRotation=baselineQ[t];transforms[t].localScale=baselineS[t];}
       for(int c=0;c<input.channels.Length;c++){
        var target=targets[c];var parts=input.channels[c].Split('.');int axis="xyzw".IndexOf(parts[1]);float v=input.samples[frame*input.channels.Length+c];
        if(float.IsNaN(v)||float.IsInfinity(v))throw new Exception("Invalid generic sample");
        if(parts[0]=="position"){var x=target.localPosition;x[axis]=v;target.localPosition=x;}
        else if(parts[0]=="rotation"){var x=target.localRotation;x[axis]=v;target.localRotation=x;}
        else if(parts[0]=="euler"){var x=target.localEulerAngles;x[axis]=v;target.localEulerAngles=x;}
        else if(parts[0]=="scale"){var x=target.localScale;x[axis]=v;target.localScale=x;}
       }
       foreach(var target in targets)target.localRotation=target.localRotation.normalized;
       handler.GetHumanPose(ref pose);
       int offset=frame*baked.channels.Length;Array.Copy(pose.muscles,0,baked.samples,offset,pose.muscles.Length);offset+=pose.muscles.Length;
       var p=pose.bodyPosition;var q=pose.bodyRotation;var body=new[]{p.x,p.y,p.z,q.x,q.y,q.z,q.w};Array.Copy(body,0,baked.samples,offset,7);
      }else for(int c=0;c<input.channels.Length;c++){
       float value=input.samples[frame*input.channels.Length+c];
       if(float.IsNaN(value)||float.IsInfinity(value))throw new Exception("Non-finite pose sample");
       if(muscles[c]>=0){pose.muscles[muscles[c]]=value;continue;}
       switch(input.channels[c]){
        case "RootT.x":pose.bodyPosition.x=value;break;case "RootT.y":pose.bodyPosition.y=value;break;case "RootT.z":pose.bodyPosition.z=value;break;
        case "RootQ.x":pose.bodyRotation.x=value;break;case "RootQ.y":pose.bodyRotation.y=value;break;case "RootQ.z":pose.bodyRotation.z=value;break;case "RootQ.w":pose.bodyRotation.w=value;break;
       }
      }
      pose.bodyRotation=pose.bodyRotation.normalized;handler.SetHumanPose(ref pose);
      foreach(var t in nodes){var p=t.localPosition;var q=t.localRotation;output.Write(p.x);output.Write(p.y);output.Write(p.z);output.Write(q.x);output.Write(q.y);output.Write(q.z);output.Write(q.w);}
     }
    }
    if(input.generic)File.WriteAllText(Option("--pose-out")+".humanoid.json",JsonUtility.ToJson(baked));
   }
   var report=new PoseOutput{name=input.name,fps=input.fps,duration=input.duration,frameCount=input.frameCount,boneCount=nodes.Length,nodes=nodes.Select(t=>Array.IndexOf(transforms,t)).ToArray(),ignoredChannels=input.channels.Where((c,i)=>muscles[i]<0&&!c.StartsWith("RootT.")&&!c.StartsWith("RootQ.")).ToArray()};
   File.WriteAllText(Option("--pose-out")+".json",JsonUtility.ToJson(report));
   Debug.Log("SCSP_POSE_WORKER_OK frames="+input.frameCount+" bones="+nodes.Length);Application.Quit(0);
  }catch(Exception ex){Debug.LogException(ex);Application.Quit(1);}
 }
}
