"""Local catalog browser. Uses the existing SCSP decoder and verified downloader."""
from __future__ import annotations

import argparse
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import os
import stat
import threading
from urllib.parse import parse_qs, urlsplit, unquote, quote
import uuid
import zipfile

import scsp_download as core
from audio_companions import with_audio_pairs
from song_delivery import select_companions, mouth_candidates
from scsp_anim_export import export_animations
from scsp_scene_export import export_scenes, has_scene
from scsp_scene_fbx import export_scene_fbx
from scsp_scene_names import scene_names
from scsp_model_export import export_models, is_model
from scsp_texture_export import export_textures
from scsp_audio_export import export_audio
from scsp_audio_index import AudioIndex
from scsp_mouth_export import export_mouth
from scsp_preview import Previews
from scsp_image_preview import ImagePreviews
from scsp_listen import Listens
from scsp_motion_preview import MotionPreviews, supports_motion, MODEL as MOTION_MODEL
from scsp_wardrobe import Wardrobe, Thumbnails

from runtime_paths import app_root
ROOT = app_root()
FINISHED = {'completed', 'failed', 'canceled', 'interrupted'}
from resource_taxonomy import CATEGORIES, CATEGORY_INFO, classify_resource, character_hint


def classify(entry):
    return classify_resource(entry)['category']


class Catalog:
    def __init__(self, data):
        if data.get("schema") != 1:
            raise core.DownloadError("不支持的索引格式")
        self.data = data
        self.entries = data["entries"]
        self.by_id = {e["id"]: e for e in self.entries}
        self.character_names, formations = {}, {}
        character_path = ROOT / 'character-data.json'
        if character_path.is_file():
            characters = json.loads(character_path.read_text(encoding='utf-8'))
            if (characters.get('game_version'), characters.get('resource_version')) == (data['game_version'], data['resource_version']):
                self.character_names = characters['characters']
                formations = characters['formations']
        self.songs = core.discover_songs(self.entries)
        self.song_codes = {song['code'] for song in self.songs}
        for song in self.songs: song['mouth_candidates'] = mouth_candidates(self.entries,song['code'])
        self.classifications = {e['id']: classify_resource(e, self.song_codes) for e in self.entries}
        self.rows = []
        for e in sorted(self.entries, key=lambda e: e["name"].lower()):
            row = dict(id=e["id"], name=e["name"], type=e["type"], size=e["size"],
                       dependencies=len(e["dependencies"]), **self.classifications[e["id"]], character=character_hint(e))
            row['character_name'] = self.character_names.get(row['character'], '')
            row['motion_preview'] = supports_motion(e)
            self.rows.append((row, " ".join([e["id"], e["name"], *e["contents"], CATEGORIES[row["category"]], row['character_name'], row['character_name'].replace(' ', '')]).casefold()))
        audio_by_code = defaultdict(list)
        for entry in self.entries:
            if entry['type'] not in ('acb', 'awb'):
                continue
            name = entry['name'].rsplit('/', 1)[-1].lower()
            match = re.match(r'^(\d{3}_[a-z0-9]+)(?:_|\.)', name)
            if match:
                audio_by_code[match[1]].append(dict(id=entry['id'], name=entry['name'],
                    size=entry['size'], type=entry['type'], category=self.classifications[entry['id']]['category']))
        for song in self.songs:
            formation = formations.get(song['code'], {})
            song['default_lineup'] = formation.get('members', [])
            song['formation_source'] = formation.get('source', '')
            song['formation_basis'] = formation.get('position_basis', '')
            song['audio'] = sorted(audio_by_code[song['code']], key=lambda a: (
                a['name'].rsplit('/', 1)[-1].lower() != song['code'] + '.acb', a['name']))
        official_songs = {}
        names_path = ROOT / 'song-names.json'
        if names_path.is_file():
            names = json.loads(names_path.read_text(encoding='utf-8'))
            if (names.get('game_version'), names.get('resource_version')) == (data['game_version'], data['resource_version']):
                official_songs = names['songs']
                for song in self.songs:
                    song.update(names['songs'].get(song['code'], {}))
        scene_labels = scene_names(self.entries, self.classifications, official_songs)
        self.rows = [(dict(row, **scene_labels.get(row['id'], {})), text+' '+
            ' '.join([scene_labels.get(row['id'], {}).get('display_name',''),
                      *scene_labels.get(row['id'], {}).get('related_song_titles',[]),
                      *scene_labels.get(row['id'], {}).get('scene_aliases',[])]).casefold())
            for row,text in self.rows]
        self.row_by_id = {r["id"]:r for r,_ in self.rows}
        self.audio_indexer = None
        self.wardrobe = Wardrobe(self, ROOT / 'wardrobe-data.json')

    def metadata(self):
        counts = Counter(r["category"] for r, _ in self.rows)
        return {**{k: v for k, v in self.data.items() if k not in ("entries", "unmapped_hashes")},
                "entry_count": len(self.entries), "categories": [dict(id=k, label=v, scope=CATEGORY_INFO[k][1], count=counts[k]) for k, v in CATEGORIES.items()],
                "types": sorted({e["type"] for e in self.entries}),
                "characters": sorted({r["character"] for r, _ in self.rows if r["character"]}),
                "character_names": self.character_names,
                "song_count": len(self.songs), "classification_version": 3,
                "audio_role_index": self.audio_indexer.status() if self.audio_indexer else None,
                "scope_counts": dict(Counter(r["scope"] for r, _ in self.rows))}

    def search(self, query="", category="", kind="", character="", page=1, sort="name", scope=""):
        if scope not in ("", "model", "motion", "scene", "audio", "other"):
            raise core.DownloadError("未知资源范围")
        terms = query.casefold().split()
        found = [r for r, text in self.rows if (not category or r["category"] == category)
                 and (not scope or r["scope"] == scope) and (not kind or r["type"] == kind) and (not character or r["character"] == character or character in r.get("audio_character_ids", []))
                 and all(term in text + " " + r.get("audio_character_search", "") for term in terms)]
        if sort == "size":
            found.sort(key=lambda r: (-r["size"], r["name"]))
        page = max(1, page)
        return {"total": len(found), "page": page, "page_size": 30, "items": found[(page-1)*30:page*30], "audio_role_index": self.audio_indexer.status() if self.audio_indexer else None}

    def plan(self, selection):
        ids = selection.get("ids", [])
        slots = selection.get("slots", [])
        code = selection.get("song_code", "")
        if not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(i, str) or i not in self.by_id for i in ids):
            raise core.DownloadError("请选择索引中的资源（最多100个直接选择项）")
        if not isinstance(slots, list) or len(slots) > 99 or any(type(i) is not int for i in slots):
            raise core.DownloadError("站位应为整数列表")
        if not isinstance(code, str) or (slots and not code):
            raise core.DownloadError("站位需要同时指定歌曲")
        selected = {i: self.by_id[i] for i in ids}
        song = None
        if code:
            entries, song = core.select_song(self.entries, code, slots)
            entries, song = select_companions(entries, song, selection.get("song_options"))
            selected.update({e["id"]: e for e in entries})
        include_raw = selection.get("include_raw",True)
        if type(include_raw) is not bool: raise core.DownloadError("保留原始资源选项应为布尔值")
        if not selected:
            raise core.DownloadError("请先选择资源或歌曲")
        planned, missing = core.resolve_dependencies(self.entries, with_audio_pairs(self.entries, list(selected.values())))
        if song:
            missing = sorted(set(missing + song["missing_companions"]))
        unique = {e["file"]: e for e in planned}
        result = dict(game_version=self.data["game_version"], resource_version=self.data["resource_version"],
                      selected_ids=list(selected), total_bytes=sum(e["size"] for e in unique.values()),
                      unique_files=len(unique), dependency_complete=not missing,
                      unresolved_dependencies=missing, entries=planned)
        result['scene_export_requested'] = has_scene(result)
        scene_format = selection.get('scene_export_format','unity')
        if scene_format not in ('unity','fbx'):
            raise core.DownloadError('场景导出格式应为 unity 或 fbx')
        result['scene_export_format'] = scene_format
        result['scene_fbx_only'] = result['scene_export_requested'] and scene_format=='fbx' and all(e['type']=='unity' for e in selected.values())
        result['model_only'] = all(is_model(e) or e['type']=='png' for e in selected.values())
        result["include_raw"] = include_raw
        result["cleanup_work"] = not include_raw
        result["convert_generic_humanoid"] = selection.get("convert_generic_humanoid",False)
        if type(result["convert_generic_humanoid"]) is not bool: raise core.DownloadError("转换人形选项应为布尔值")
        if song:
            result["song_selection"] = song
        if self.data.get("source_kind") == "public_snapshot":
            result["snapshot_provenance"] = {k: v for k, v in self.data.items() if k not in ("entries", "unmapped_hashes")}
        return result


def plan_summary(plan):
    return {**{k: v for k, v in plan.items() if k not in ("entries", "unresolved_dependencies")},
            "entry_count": len(plan["entries"]), "missing_count": len(plan["unresolved_dependencies"]),
            "unresolved_dependencies": plan["unresolved_dependencies"][:100],
            "items": [dict(id=e["id"], name=e["name"], size=e["size"], type=e["type"]) for e in plan["entries"][:100]]}


from scsp_job_state import JobRecovery


class Downloads(JobRecovery):
    def __init__(self, catalog, output, cache):
        self.catalog, self.output, self.cache = catalog, Path(output).resolve(), Path(cache).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.jobs = {}
        for path in self.output.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job.get('hidden'):
                    continue
                if re.fullmatch(r"[a-f0-9]{12}", job["id"]):
                    if job["status"] in ("queued", "running", "canceling", "exporting", "packaging"):
                        job.update(status="interrupted", error="上次服务退出，任务未完成；可点击继续任务，已校验文件会复用。")
                    self.jobs[job["id"]] = job
            except (OSError, ValueError, KeyError):
                continue

    def update(self, job, **values):
        with self.lock:
            job.update(values)
            core.write_json(self.output / job["id"] / "job.json", job)

    def listing(self):
        with self.lock:
            for job in self.jobs.values():
                if job['status'] in FINISHED and job.get('stored_bytes') is None:
                    try:
                        job['stored_bytes'] = self.storage_bytes(job['id'])
                    except (OSError, core.DownloadError):
                        job['stored_bytes'] = None
            return json.loads(json.dumps(list(reversed(list(self.jobs.values())))))

    def task_paths(self, identity):
        if not re.fullmatch(r'[a-f0-9]{12}', identity):
            raise core.DownloadError('无效任务编号')
        paths = [self.output / identity, self.output / (identity + '.zip'), self.output / (identity + '.zip.part')]
        for path in paths:
            if not path.resolve().is_relative_to(self.output) or path.resolve() == self.output:
                raise core.DownloadError('任务路径超出下载目录，拒绝清理')
            if path.is_symlink() or (path.exists() and getattr(path.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise core.DownloadError('任务路径含链接或联接，拒绝清理')
        return paths

    def storage_bytes(self, identity):
        folder, *archives = self.task_paths(identity)
        total = sum(p.stat().st_size for p in archives if p.is_file())
        if folder.exists():
            for current, directories, files in os.walk(folder, followlinks=False):
                for name in directories + files:
                    path = Path(current) / name
                    if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        raise core.DownloadError('任务内部含链接或联接，拒绝清理')
                total += sum((Path(current) / name).stat().st_size for name in files)
        return total

    def remove(self, identity, delete_files):
        if type(delete_files) is not bool:
            raise core.DownloadError('删除文件选项应为布尔值')
        with self.lock:
            job = self.jobs.get(identity)
            if not job:
                raise core.DownloadError('任务不存在或已清理')
            if job['status'] not in FINISHED:
                raise core.DownloadError('进行中的任务不能清理，请先取消并等待结束')
            folder, *archives = self.task_paths(identity)
            freed = 0
            if delete_files:
                freed = self.storage_bytes(identity)  # Validate the whole tree before deletion.
                for archive in archives:
                    archive.unlink(missing_ok=True)
                if folder.exists():
                    shutil.rmtree(folder)
            else:
                self.update(job, hidden=True)
            del self.jobs[identity]
            return dict(id=identity, delete_files=delete_files, freed_bytes=freed)

    def clear(self, identities, delete_files):
        if not isinstance(identities, list) or not identities or len(identities) > 1000 or any(not isinstance(i, str) for i in identities):
            raise core.DownloadError('请选择1～1000个已结束任务')
        if type(delete_files) is not bool:
            raise core.DownloadError('删除文件选项应为布尔值')
        removed, errors = [], []
        for identity in dict.fromkeys(identities):
            try:
                removed.append(self.remove(identity, delete_files))
            except (OSError, core.DownloadError) as error:
                errors.append(dict(id=identity, error=str(error)))
        return dict(removed=removed, errors=errors, freed_bytes=sum(r['freed_bytes'] for r in removed))

    def submit(self, request):
        allow = request.get("allow_unresolved", False)
        limit = request.get("max_total_mb", 256)
        if type(allow) is not bool or type(limit) not in (int, float) or not 1 <= limit <= 4096:
            raise core.DownloadError("下载上限应为1～4096 MiB；缺项选项应为布尔值")
        plan = self.catalog.plan(request)
        if not plan["dependency_complete"] and not allow:
            raise core.DownloadError("存在依赖缺项。查看计划后，勾选“允许带缺项下载”才能继续。")
        if plan["total_bytes"] > limit * 1048576:
            raise core.DownloadError("计划超过下载体积上限，请减少选择或调整上限")
        with self.lock:
            if sum(j["status"] in ("queued", "running", "canceling", "exporting", "packaging") for j in self.jobs.values()) >= 5:
                raise core.DownloadError("最多同时保留5个待处理任务")
            job = dict(id=uuid.uuid4().hex[:12], status="queued", completed_files=0, total_files=plan["unique_files"],
                       completed_bytes=0, total_bytes=plan["total_bytes"], current="", error="",
                       dependency_complete=plan["dependency_complete"], missing_count=len(plan["unresolved_dependencies"]),
                       selected_ids=plan["selected_ids"], animation_count=0, output_path="",
                       scene_export_format=plan['scene_export_format'],phase='queued',attempt=1)
            self.jobs[job["id"]] = job
            self.update(job, output_path=str(self.output / job["id"]))
            self.pool.submit(self.run, job, plan)
            return dict(job)

    def cancel(self, identity):
        with self.lock:
            job = self.jobs.get(identity)
            if not job:
                raise core.DownloadError("任务不存在")
            if job["status"] in ("queued", "running"):
                self.update(job, status="canceling")
            return dict(job)

    def run(self, job, plan):
        output = self.output / job["id"]
        plan = {**plan, "outputs": list(plan.get("outputs",[])), "download_complete": False}
        plan.pop("download_error",None)
        core.write_json(output / "manifest.json", plan)
        try:
            if job["status"] == "canceling":
                self.update(job, status="canceled")
                return
            valid=self.valid_inputs(output,plan)
            if job.get('retry_mode')=='export' and len(valid)!=len({e['file'] for e in plan['entries']}):
                raise core.DownloadError('原始输入在排队期间发生变化，请使用继续任务')
            plan['outputs']=list(valid.values())
            self.update(job,status='running',phase='downloading',phase_label='下载资源',
                completed_files=len(valid),completed_bytes=sum(e['size'] for e in {e['file']:e for e in plan['entries']}.values() if e['file'] in valid),
                cached_files=0,cached_bytes=0,reused_files=len(valid),network_bytes=0,downloaded_files=0,retry_count=0,reused_stages=0,speed_bps=0)
            started=time.monotonic()
            def transfer(kind,details):
                if kind=='cache':self.update(job,cached_files=job['cached_files']+1,cached_bytes=job['cached_bytes']+details['bytes'])
                elif kind=='received':
                    count=job['network_bytes']+details['bytes']
                    self.update(job,network_bytes=count,speed_bps=count/max(.001,time.monotonic()-started))
                elif kind=='downloaded':self.update(job,downloaded_files=job['downloaded_files']+1)
                elif kind=='retry':self.update(job,retry_count=job['retry_count']+1,current=f"重试 {details['attempt']}/{details['max_attempts']} · 等待 {details['delay']} 秒 · {job.get('resource_name','')}")
            for entry in {e["file"]: e for e in plan["entries"]}.values():
                with self.lock:
                    if job["status"] == "canceling":
                        self.update(job, status="canceled", current="")
                        return
                if entry['file'] in valid:continue
                self.update(job,current=entry['name'],resource_name=entry['name'])
                with core.transfer_observer(transfer):
                    decoded=core.decode_asset(entry,core.get_file(entry,self.cache))
                relative = (f"bundles/{entry['file']}.unity3d" if entry["resource_type"] in (0, 1) else f"raw/{entry['id']}")
                path = core.safe_output(output, relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():self.preserve(job,[relative])
                temp = path.with_suffix(path.suffix + ".part")
                temp.write_bytes(decoded)
                temp.replace(path)
                plan["outputs"].append(dict(file=entry["file"], output=relative, sha256=hashlib.sha256(decoded).hexdigest()))
                core.write_json(output / "manifest.json", plan)
                self.update(job, completed_files=len(plan["outputs"]), completed_bytes=job["completed_bytes"] + entry["size"])
            with self.lock:
                if job["status"] == "canceling":
                    self.update(job, status="canceled", current="")
                    return
            self.update(job,status="exporting",phase="exporting",current="正在检查并导出所选资源")
            scene_exporter = export_scene_fbx if plan.get('scene_export_format')=='fbx' else export_scenes
            scene_report=self.stage(job,plan,'scene','导出场景',lambda:scene_exporter(output,progress=lambda text:self.update(job,current=text)),0)
            plan["scene_export"] = scene_report
            self.update(job, scene_count=len(scene_report["scenes"]), scene_files=scene_report["scenes"], scene_warnings=scene_report.get('warnings',[]))
            model_only = plan.get('model_only', False)
            animation_report=self.stage(job,plan,'animation','导出动作',lambda:({'sources':[],'clips':[]} if model_only or scene_report['scenes'] else export_animations(output,progress=lambda text:self.update(job,current=text))),1)
            plan['animation_export']=animation_report
            self.update(job,animation_count=len(animation_report['clips']),animation_files=[c['file'] for c in animation_report['clips']])
            def models():
                report=export_models(output,progress=lambda text:self.update(job,current=text))
                if model_only:
                    texture_files=export_textures(output);report['files'].extend(texture_files)
                    if texture_files:core.write_json(output/'models/export-report.json',report)
                return report
            model_report=self.stage(job,plan,'model','导出模型与贴图',models,2)
            plan['model_export'] = model_report
            self.update(job, model_files=[f['file'] for f in model_report['files']+scene_report['files'] if f['file'].lower().endswith('.fbx')],
                        model_count=sum(len(m['fbxs']) for m in model_report['models']))
            audio_report=self.stage(job,plan,'audio','转换音频',lambda:({'files':[]} if model_only else export_audio(output,progress=lambda text:self.update(job,current=text))),3)
            self.update(job,animation_count=len(animation_report['clips']),animation_files=[c['file'] for c in animation_report['clips']],audio_count=len(audio_report['files']),audio_files=[a['file'] for a in audio_report['files']])
            plan['audio_export'] = audio_report
            self.update(job,export_warnings=animation_report.get('warnings',[]))
            mouth_report=self.stage(job,plan,'mouth','导出口型',lambda:({'files':[]} if model_only else export_mouth(output,progress=lambda text:self.update(job,current=text))),4)
            plan['mouth_export'] = mouth_report
            self.update(job,export_warnings=animation_report.get('warnings',[])+mouth_report.get('warnings',[]))
            self.update(job, mouth_files=[a['file'] for a in mouth_report['files']], mouth_count=len(mouth_report['files']))
            self.update(job, animation_count=len(animation_report["clips"]), animation_files=[c["file"] for c in animation_report["clips"]], audio_files=[a['file'] for a in audio_report['files']], audio_tracks=audio_report['files'], audio_count=len(audio_report['files']), status="packaging", current="正在打包场景工程与原始资源" if scene_report["scenes"] else "正在打包原始资源、FBX、anim与WAV")
            plan["download_complete"] = True
            core.write_json(output / "manifest.json", plan)
            self.package(job,plan,scene_report,animation_report,model_report,audio_report,mouth_report)
            if model_only or not plan.get('include_raw',True):
                # Only after successful delivery: preserve shared cache and failure evidence.
                folder, *_ = self.task_paths(job['id'])
                self.storage_bytes(job['id'])  # Reject links/reparse points before recursive cleanup.
                for name in ('bundles', 'raw', 'model-export-work'):
                    path = folder / name
                    if path.exists():
                        shutil.rmtree(path)
                plan['temporary_inputs_removed'] = True
                core.write_json(output / 'manifest.json', plan)
                self.update(job, model_only=model_only)
            self.update(job,status="completed",phase="completed",phase_label="已完成",current="",phase_completed=1,phase_total=1,stored_bytes=None)
        except Exception as exc:
            core.write_json(output / "manifest.json", {**plan, "download_error": str(exc), "download_complete": False})
            self.update(job,status="failed",error=str(exc),current="",stored_bytes=None)


def make_handler(catalog, downloads, index_path=None, previews=None, listens=None, motions=None, audio_index=None, images=None):
    thumbnails = Thumbnails(catalog, ROOT / 'wardrobe-thumbnails', downloads.cache)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if args and str(args[1]) not in ("200", "304"):
                super().log_message(fmt, *args)

        def json_response(self, value, status=200):
            blob = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(blob)

        def do_GET(self):
            try:
                parsed = urlsplit(self.path)
                params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                texture_match = re.fullmatch(r'/api/motion-textures/([a-f0-9]{16}\.png)', parsed.path)
                if texture_match and motions:
                    return self.file_response(MOTION_MODEL.parent/'textures'/texture_match[1], 'image/png', cache_control='private, max-age=31536000, immutable')
                if parsed.path == '/api/motion-model' and motions:
                    return self.file_response(MOTION_MODEL, 'application/json', cache_control='private, max-age=86400')
                motion_match = re.fullmatch(r'/api/motions/([a-f0-9]{24})(/(motion\.(?:json|bin)|mouth\.json|converted\.anim))?', parsed.path)
                if motion_match and motions:
                    job = motions.get(motion_match[1])
                    if not motion_match[2]:
                        return self.json_response(job)
                    if job['status'] != 'completed':
                        return self.json_response({'error':'动作预览尚未就绪'},409)
                    return self.file_response(motions.root/job['key']/motion_match[3], 'application/json' if motion_match[3].endswith('.json') else 'application/octet-stream', cache_control='no-store')
                if parsed.path == '/api/audio-index' and audio_index:
                    return self.json_response(audio_index.status())
                if parsed.path == '/api/audio-index/bank' and audio_index:
                    record = audio_index.bank(params.get('id', ''))
                    return self.json_response(record if record else {'indexed':False, 'message':'此包的Cue索引尚未完成；不会按剧情编号猜角色'})
                image_match = re.fullmatch(r'/api/images/([a-f0-9]{24})(/image.png)?', parsed.path)
                if image_match and images:
                    job=images.get(image_match[1])
                    if not image_match[2]:return self.json_response(job)
                    if job['status']!='completed':return self.json_response({'error':'图片尚未就绪'},409)
                    return self.file_response(images.root/job['key']/'image.png','image/png',cache_control='no-store')
                if parsed.path == "/api/meta":
                    return self.json_response(catalog.metadata())
                if parsed.path == '/api/wardrobe/meta':
                    return self.json_response(catalog.wardrobe.metadata())
                if parsed.path == '/api/wardrobe':
                    return self.json_response(catalog.wardrobe.search(params.get('character','12'), params.get('group','dress'), params.get('category',''), params.get('q','')[:300], int(params.get('page',1))))
                if parsed.path == '/api/wardrobe/icon':
                    thumbnails.catalog = catalog
                    entry = catalog.by_id.get(params.get('id',''),{})
                    policy = 'private, max-age=31536000, immutable' if params.get('v')==entry.get('file') else 'no-store'
                    return self.file_response(thumbnails.get(params.get('id','')), 'image/png', cache_control=policy)
                if parsed.path == "/api/resources":
                    return self.json_response(catalog.search(params.get("q", "")[:300], params.get("category", ""),
                        params.get("type", ""), params.get("character", ""), int(params.get("page", 1)), params.get("sort", "name"), params.get("scope", "")))
                if parsed.path == "/api/songs":
                    query = params.get("q", "").casefold()
                    return self.json_response([s for s in catalog.songs if query in ' '.join(
                        str(s.get(key, '')) for key in ('code', 'title', 'artist', 'reading')).casefold()])
                if parsed.path == "/api/resource":
                    entry = catalog.by_id.get(params.get("id", ""))
                    if not entry:
                        return self.json_response({"error": "资源不存在"}, 404)
                    return self.json_response({**catalog.row_by_id[entry['id']],
                        **{k: entry[k] for k in ("id", "name", "type", "size", "contents", "dependencies")}})
                if parsed.path == "/api/jobs":
                    return self.json_response(downloads.listing())
                audition = re.fullmatch(r'/api/listens/([a-f0-9]{24})(/track/(\d+))?', parsed.path)
                if audition and listens:
                    job = listens.get(audition[1])
                    if audition[2]:
                        track = next((t for t in job.get('tracks', []) if t['track'] == int(audition[3])), None)
                        if job['status'] != 'completed' or not track:
                            return self.json_response({'error': '音轨尚未生成'}, 404)
                        return self.file_response(listens.track_file(audition[1],int(audition[3])) if hasattr(listens,'track_file') else core.safe_output(listens.root / audition[1], track['file']), 'audio/wav', ranges=True)
                    return self.json_response(job)
                preview = re.fullmatch(r'/api/previews/([a-f0-9]{24})(/model.glb)?', parsed.path)
                if preview and previews:
                    job = previews.get(preview[1])
                    if preview[2]:
                        if job['status'] != 'completed':
                            return self.json_response({'error': '模型预览尚未生成'}, 409)
                        return self.file_response(previews.root / preview[1] / 'model.glb', 'model/gltf-binary')
                    return self.json_response(job)
                match = re.fullmatch(r"/api/jobs/([a-f0-9]{12})/(archive|manifest)", parsed.path)
                if match:
                    job = downloads.jobs.get(match[1])
                    if not job:
                        return self.json_response({"error": "任务不存在"}, 404)
                    if match[2] == "archive" and job["status"] != "completed":
                        return self.json_response({"error": "下载尚未完成"}, 409)
                    path = downloads.output / (match[1] + ".zip") if match[2] == "archive" else downloads.output / match[1] / "manifest.json"
                    return self.file_response(path, "application/zip" if match[2] == "archive" else "application/json", True)
                mouth_match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/mouth/([^/]+)', parsed.path)
                if mouth_match:
                    job = downloads.jobs.get(mouth_match[1])
                    relative = 'mouth/' + unquote(mouth_match[2])
                    if not job or job['status'] != 'completed' or relative not in job.get('mouth_files', []):
                        return self.json_response({'error': '口型JSON不存在或任务尚未完成'}, 404)
                    return self.file_response(core.safe_output(downloads.output / job['id'], relative), 'application/json', True)
                audio_match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/audio/([^/]+)', parsed.path)
                if audio_match:
                    job = downloads.jobs.get(audio_match[1])
                    relative = 'audio/' + unquote(audio_match[2])
                    if not job or job['status'] != 'completed' or relative not in job.get('audio_files', []):
                        return self.json_response({'error': 'WAV不存在或任务尚未完成'}, 404)
                    return self.file_response(core.safe_output(downloads.output / job['id'], relative), 'audio/wav', True)
                model_match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/model/(\d+)', parsed.path)
                if model_match:
                    job = downloads.jobs.get(model_match[1])
                    model_index = int(model_match[2])
                    if not job or job['status'] != 'completed' or model_index >= len(job.get('model_files', [])):
                        return self.json_response({'error': '模型不存在或任务尚未完成'}, 404)
                    return self.file_response(core.safe_output(downloads.output / job['id'], job['model_files'][model_index]), 'application/octet-stream', True)
                animation_match = re.fullmatch(r"/api/jobs/([a-f0-9]{12})/animation/([^/]+)", parsed.path)
                if animation_match:
                    job = downloads.jobs.get(animation_match[1])
                    name = unquote(animation_match[2])
                    relative = "animations/" + name
                    if not job or job["status"] != "completed" or relative not in job.get("animation_files", []):
                        return self.json_response({"error": "动画不存在或任务尚未完成"}, 404)
                    return self.file_response(core.safe_output(downloads.output / job["id"], relative), "application/octet-stream", True)
                files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                         '/wardrobe': ('wardrobe.html', 'text/html; charset=utf-8'),
                         '/wardrobe.js': ('wardrobe.js', 'text/javascript; charset=utf-8'),
                         '/wardrobe.css': ('wardrobe.css', 'text/css; charset=utf-8'),
                         '/preview.js': ('preview.js', 'text/javascript; charset=utf-8'),
                         '/motion-viewer.js': ('motion-viewer.js', 'text/javascript; charset=utf-8'),
                         '/image-preview-ui.js': ('image-preview-ui.js', 'text/javascript; charset=utf-8'),
                         **{'/vendor/' + name: ('vendor/' + name, 'text/javascript; charset=utf-8') for name in
                            ('three.module.js', 'GLTFLoader.js', 'OrbitControls.js', 'BufferGeometryUtils.js')},
                         "/style.css": ("style.css", "text/css; charset=utf-8")}
                if parsed.path in files:
                    name, mime = files[parsed.path]
                    return self.file_response(ROOT / "web" / name, mime)
                return self.json_response({"error": "页面不存在"}, 404)
            except (ValueError, OSError) as exc:
                self.json_response({"error": str(exc)}, 400)

        def file_response(self, path, mime, attachment=False, ranges=False, cache_control=None):
            if not path.is_file():
                return self.json_response({"error": "文件不存在"}, 404)
            size = path.stat().st_size
            start, end = 0, size - 1
            partial = ranges and bool(self.headers.get('Range'))
            if partial:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers['Range'])
                if not match or not any(match.groups()):
                    self.send_response(416);self.send_header('Content-Range', f'bytes */{size}');self.end_headers();return
                if match[1]:
                    start = int(match[1]);end = min(int(match[2]), end) if match[2] else end
                else:
                    start = max(0, size-int(match[2]))
                if start > end or start >= size:
                    self.send_response(416);self.send_header('Content-Range', f'bytes */{size}');self.end_headers();return
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", mime)
            if cache_control:
                self.send_header('Cache-Control', cache_control)
            self.send_header("Content-Length", str(end-start+1))
            if ranges:
                self.send_header('Accept-Ranges', 'bytes')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.send_header("X-Content-Type-Options", "nosniff")
            if attachment:
                self.send_header("Content-Disposition", f'attachment; filename="download{path.suffix}"; filename*=UTF-8\'\'{quote(path.name)}')
            self.end_headers()
            try:
                with path.open("rb") as source:
                    source.seek(start)
                    remaining = end-start+1
                    while remaining and (chunk := source.read(min(1024 * 1024, remaining))):
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            nonlocal catalog, audio_index
            try:
                # JSON + explicit header prevent another site from starting local downloads.
                host = self.headers.get("Host", "")
                origin = self.headers.get("Origin")
                valid_hosts = (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")
                if host not in valid_hosts or self.headers.get("X-SCSP-Client") != "1" or self.headers.get("Content-Type", "").split(";")[0] != "application/json" or (origin and origin != "http://" + host):
                    return self.json_response({"error": "仅接受本地页面提交的JSON请求"}, 403)
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 65536:
                    raise core.DownloadError("请求大小无效")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise core.DownloadError("请求应为JSON对象")
                if self.path == '/api/audio-index' and audio_index:
                    action = body.get('action', 'start')
                    if action == 'pause':
                        audio_index.stop.set()
                        return self.json_response(audio_index.status())
                    if action != 'start': raise ValueError('未知角色索引操作')
                    return self.json_response(audio_index.start(), 202)
                if self.path == '/api/reload':
                    new_catalog = Catalog(json.loads(Path(index_path or ROOT / 'official-current-index.json').read_text(encoding='utf-8')))
                    with downloads.lock:
                        if any(j['status'] in ('queued', 'running', 'canceling', 'exporting', 'packaging') for j in downloads.jobs.values()):
                            return self.json_response({'error': '有活动下载任务，请完成后再重载目录'}, 409)
                        if audio_index:
                            audio_index.close()
                            audio_index = AudioIndex(new_catalog, audio_index.root, audio_index.cache)
                            audio_index.start()
                        catalog = new_catalog
                        downloads.catalog = new_catalog
                        if previews:
                            previews.catalog = new_catalog
                        if listens:
                            listens.catalog = new_catalog
                        if motions:
                            motions.catalog = new_catalog
                        if images:
                            images.catalog = new_catalog
                    return self.json_response({'reloaded': True, 'entry_count': len(catalog.entries), 'song_count': len(catalog.songs)})
                if self.path == "/api/plan":
                    return self.json_response(plan_summary(catalog.plan(body)))
                if self.path == "/api/download":
                    return self.json_response(downloads.submit(body), 202)
                if self.path == '/api/image-preview' and images:
                    return self.json_response(images.start(body.get('id')),202)
                if self.path == '/api/preview' and previews:
                    return self.json_response(previews.start(body.get('id')), 202)
                if self.path == '/api/motion-preview' and motions:
                    return self.json_response(motions.start(body.get('id')), 202)
                if self.path == '/api/listen' and listens:
                    return self.json_response(listens.start(body.get('id')), 202)
                release = re.fullmatch(r'/api/(previews|listens|motions|images)/([a-f0-9]{24})/release', self.path)
                if release:
                    manager = {'previews':previews,'listens':listens,'motions':motions,'images':images}[release[1]]
                    if manager:
                        return self.json_response(manager.release(release[2]))
                if self.path == '/api/jobs/clear':
                    return self.json_response(downloads.clear(body.get('ids'), body.get('delete_files', False)))
                retry = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/retry',self.path)
                if retry:
                    return self.json_response(downloads.retry(retry[1],body.get('mode','resume')),202)
                deletion = re.fullmatch(r'/api/jobs/([a-f0-9]{12})/remove', self.path)
                if deletion:
                    return self.json_response(downloads.remove(deletion[1], body.get('delete_files', False)))
                match = re.fullmatch(r"/api/jobs/([a-f0-9]{12})/cancel", self.path)
                if match:
                    return self.json_response(downloads.cancel(match[1]))
                return self.json_response({"error": "接口不存在"}, 404)
            except (ValueError, OSError, TypeError) as exc:
                self.json_response({"error": str(exc)}, 400)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=(ROOT / "official-current-index.json" if (ROOT / "official-current-index.json").is_file() else ROOT / "latest-index.json"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--out", type=Path, default=ROOT / "web-downloads")
    args = parser.parse_args()
    print("正在加载本地资源索引…", flush=True)
    catalog = Catalog(json.loads(args.index.read_text(encoding="utf-8")))
    downloads = Downloads(catalog, args.out, ROOT / ".scsp-cache")
    previews = Previews(catalog, ROOT / 'model-previews', ROOT / '.scsp-cache')
    listens = Listens(catalog, ROOT / 'audio-previews', ROOT / '.scsp-cache')
    motions = MotionPreviews(catalog, ROOT / 'motion-previews', ROOT / '.scsp-cache')
    images = ImagePreviews(catalog, ROOT / 'image-previews', ROOT / '.scsp-cache')
    audio_index = AudioIndex(catalog, ROOT / 'audio-index', ROOT / '.scsp-cache')
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(catalog, downloads, args.index, previews, listens, motions, audio_index, images))
    audio_index.start()
    previews.cleanup_stale()
    listens.cleanup_stale()
    motions.cleanup_stale()
    images.cleanup_stale()
    print(f"SCSP Web 已启动：http://127.0.0.1:{server.server_port}（{len(catalog.entries):,} 个已命名资源）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if downloads.catalog.audio_indexer: downloads.catalog.audio_indexer.close()
        downloads.pool.shutdown(wait=True, cancel_futures=True)
        previews.pool.shutdown(wait=True, cancel_futures=True)
        listens.pool.shutdown(wait=True, cancel_futures=True)
        motions.pool.shutdown(wait=True, cancel_futures=True)
        images.pool.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    main()
