# -*- coding: utf-8 -*-
from __future__ import annotations

# UI-independent controller/orchestration methods reused by the PySide6 UI.
from .core import *


class GTMCEControllerMixin:
    def output_path_with_current_name_extra(self, output_path: Path) -> Path:
        output_path = output_path_with_name_extra(output_path, self.output_name_extra_var.get())
        folder_raw = self.folder_var.get().strip()
        if not self.output_name_year_var.get() or not folder_raw:
            return output_path
        media_type = self.tmdb_media_type_from_display(self.media_type_display_var.get())
        if not media_type:
            media_type = self.media_type_var.get().strip()
        return output_path_with_optional_year(
            output_path,
            enabled=True,
            media_type=media_type,
            media_dir=Path(folder_raw).expanduser(),
            extra=self.output_name_extra_var.get(),
        )

    def on_output_name_year_changed(self) -> None:
        if self.output_name_year_var.get():
            output_raw = self.output_var.get().strip()
            folder_raw = self.folder_var.get().strip()
            if output_raw and folder_raw:
                output_path = self.output_path_with_current_name_extra(Path(output_raw).expanduser())
                self.output_var.set(str(output_path))
                if (
                    not local_release_year(
                        Path(folder_raw).expanduser(),
                        output_path,
                        self.output_name_extra_var.get(),
                    )
                    and self.api_key_var.get().strip()
                ):
                    self.start_find_tmdb_id(auto=True)
        self.save_preferences()

    def existing_initial_dir(self, *candidates: str | Path | None) -> str:
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate).expanduser()
            if path.is_file():
                path = path.parent
            if path.exists() and path.is_dir():
                return str(path)
        return str(APP_DIR)

    def extract_source_initial_dir(self) -> str:
        source_raw = self.extract_source_var.get().strip()
        source_dir = Path(source_raw).expanduser().parent if source_raw else None
        return self.existing_initial_dir(
            self.last_mkv_dir,
            source_dir,
            self.folder_var.get().strip(),
            APP_DIR,
        )

    def remember_mkv_dir(self, path: Path) -> None:
        directory = path if path.is_dir() else path.parent
        self.last_mkv_dir = str(directory.expanduser())
        self.save_preferences()

    @staticmethod
    def default_extract_output_dir(source: Path) -> Path:
        source = source.expanduser()
        base_name = source.name if source.is_dir() else source.stem
        return source.parent / f"{base_name}_tracks"

    def set_extract_source(self, source: Path, *, scan: bool) -> None:
        source = source.expanduser()

        previous_source_raw = self.extract_source_var.get().strip()
        previous_output_raw = self.extract_output_dir_var.get().strip()
        update_output_dir = not previous_output_raw

        # When the extraction folder still contains the automatically generated
        # path for the previous source, follow a newly selected source as well.
        # A folder chosen manually by the user is intentionally preserved.
        if previous_source_raw and previous_output_raw:
            previous_source = Path(previous_source_raw).expanduser()
            previous_default = self.default_extract_output_dir(previous_source)
            update_output_dir = (
                os.path.normcase(os.path.abspath(previous_output_raw))
                == os.path.normcase(os.path.abspath(os.fspath(previous_default)))
            )

        self.extract_source_var.set(str(source))
        if update_output_dir:
            self.extract_output_dir_var.set(str(self.default_extract_output_dir(source)))

        self.remember_mkv_dir(source)
        if scan and source.is_file():
            self.start_scan_extract()

    def _set_default_output(self) -> None:
        folder = self.folder_var.get().strip()
        if not folder or self.output_var.get().strip():
            return
        media_dir = Path(folder).expanduser()
        template_raw = self.template_var.get().strip()
        try:
            if template_raw:
                config = load_template_config(Path(template_raw).expanduser())
            else:
                config = base_template_config()
            output_path = default_output_path(config, media_dir)
        except UserVisibleError:
            output_path = media_dir / default_output_name(base_template_config(), media_dir)
        output_path = self.output_path_with_current_name_extra(output_path)
        self.output_var.set(str(output_path))

    def collect_settings(self, *, require_tmdb: bool = False) -> AppSettings:
        template_raw = self.template_var.get().strip()
        template_path = Path(template_raw).expanduser() if template_raw else None
        folder_raw = self.folder_var.get().strip()
        media_dir = Path(folder_raw).expanduser()
        output_raw = self.output_var.get().strip()
        output_name_extra = self.output_name_extra_var.get()
        output_name_year = self.output_name_year_var.get()
        api_key = self.api_key_var.get().strip()
        tmdb_id = self.tmdb_id_var.get().strip()
        media_type = self.tmdb_media_type_from_display(self.media_type_display_var.get())
        if not media_type:
            media_type = self.media_type_var.get().strip()
        image_language = self.language_var.get().strip() or "en"
        tag_language = self.tag_language_var.get().strip() or image_language
        mkv_title = self.title_var.get().strip()
        video_fps = self.video_fps_var.get().strip()
        audio_language_order = self.audio_language_order_var.get().strip()
        subtitle_language_order = self.subtitle_language_order_var.get().strip()
        auto_chapters = self.auto_chapters_var.get()
        auto_chapter_detect_intro = self.auto_chapter_detect_intro_var.get()
        chapter_interval_minutes = self.chapter_interval_var.get().strip()
        chapter_name = self.chapter_name_var.get().strip()
        chapter_start_number = self.chapter_start_var.get().strip()
        chapter_end_minutes = self.chapter_end_var.get().strip()

        if template_path is not None and not template_path.exists():
            raise UserVisibleError(ui_text("error_template_missing", path=template_path))
        if not folder_raw or folder_raw == ".":
            raise UserVisibleError(ui_text("error_track_folder_not_selected"))
        if not media_dir.exists() or not media_dir.is_dir():
            raise UserVisibleError(ui_text("error_track_folder_not_found", path=media_dir))
        if output_raw:
            output_path = Path(output_raw).expanduser()
        else:
            config = load_or_create_template_config(template_path, media_dir)
            output_path = default_output_path(config, media_dir)
            output_path = output_path_with_optional_year(
                output_path,
                enabled=output_name_year,
                media_type=media_type,
                media_dir=media_dir,
                extra=output_name_extra,
            )
            self.log_queue.put(
                ("log", self.tr("log_output_default_used", path=output_path))
            )
            self.output_var.set(str(output_path))
        output_path = output_path_with_optional_year(
            output_path,
            enabled=output_name_year,
            media_type=media_type,
            media_dir=media_dir,
            extra=output_name_extra,
        )
        if media_type not in {"movie", "tv"}:
            raise UserVisibleError(ui_text("error_tmdb_media_type"))
        normalize_video_fps(video_fps)
        if require_tmdb:
            if not api_key:
                raise UserVisibleError(ui_text("error_tmdb_artwork_api_required"))
            if not tmdb_id:
                raise UserVisibleError(ui_text("error_tmdb_id_empty"))
            if not tmdb_id.isdigit():
                raise UserVisibleError(ui_text("error_tmdb_id_numeric"))

        return AppSettings(
            template_path=template_path,
            media_dir=media_dir,
            output_path=output_path,
            output_name_extra=output_name_extra,
            output_name_year=output_name_year,
            api_key=api_key,
            tmdb_id=tmdb_id,
            media_type=media_type,
            image_language=image_language,
            tag_language=tag_language,
            mkv_title=mkv_title,
            video_fps=video_fps,
            audio_language_order=audio_language_order,
            subtitle_language_order=subtitle_language_order,
            include_extra_subtitles=self.include_extra_subs_var.get(),
            download_before_mux=self.download_before_mux_var.get(),
            auto_chapters=auto_chapters,
            auto_chapter_detect_intro=auto_chapter_detect_intro,
            chapter_interval_minutes=chapter_interval_minutes,
            chapter_name=chapter_name,
            chapter_start_number=chapter_start_number,
            chapter_end_minutes=chapter_end_minutes,
        )

    def chapter_options_from_settings(self, settings: AppSettings) -> ChapterOptions:
        return ChapterOptions(
            enabled=settings.auto_chapters,
            detect_intro=settings.auto_chapter_detect_intro,
            interval_minutes=settings.chapter_interval_minutes,
            name=settings.chapter_name,
            start_number=settings.chapter_start_number,
            end_minutes=settings.chapter_end_minutes,
            video_fps=settings.video_fps,
        )

    def chapter_end_needs_auto_detection(self, value: str) -> bool:
        return not value.strip()

    def mux_track_customizations(
        self,
    ) -> tuple[
        list[AdditionalMuxTrack],
        list[str],
        dict[str, str],
        dict[str, str],
        dict[str, tuple[Path, ...]],
        set[str],
    ]:
        if not self.add_tracks_before_mux_var.get():
            return [], [], {}, {}, {}, set()
        return (
            list(self.additional_mux_tracks),
            list(self.mux_track_order_keys),
            dict(self.mux_track_language_overrides),
            dict(self.mux_track_delay_overrides),
            dict(self.mux_track_append_overrides),
            set(self.mux_track_excluded_keys),
        )

    def mux_track_kind_label(self, path: Path) -> str:
        kind = media_kind_from_path(path)
        if kind == "audio":
            return self.tr("track_type_audio")
        if kind == "video":
            return self.tr("track_type_video")
        if kind == "subtitle":
            return self.tr("track_type_subtitle")
        return self.tr("track_type_generic")

    def mux_asset_kind_label(self, asset_kind: str) -> str:
        labels = {
            "chapters": "chapters.txt",
            "tags": "tags.xml",
            "artwork": self.tr("track_type_artwork"),
        }
        return labels.get(asset_kind, self.tr("track_type_generic"))

    def mux_window_row_key(self, path: Path, asset_kind: str = "", target_name: str = "") -> str:
        if asset_kind:
            return f"asset:{asset_kind}:{target_name}:{path_identity_key(path)}"
        return path_identity_key(path)

    def mux_track_file_label(self, row: MuxTrackWindowRow) -> str:
        if row.asset_kind:
            if row.target_name and row.target_name != row.path.name:
                return f"{row.path.name} -> {row.target_name}"
            return row.path.name
        appended = "".join(f" + {path.name}" for path in row.append_paths)
        return f"{row.path.name}{appended}"

    def mux_track_append_supported(self, row: MuxTrackWindowRow | None) -> bool:
        return bool(
            row is not None
            and row.included
            and not row.asset_kind
            and media_kind_from_path(row.path) == "audio"
        )

    def mux_track_window_rows(self, settings: AppSettings) -> list[MuxTrackWindowRow]:
        config = load_or_create_template_config(settings.template_path, settings.media_dir)
        unknown_language = (
            normalise_language(settings.tag_language)
            if settings.tag_language
            else MUX_UNKNOWN_LANGUAGE
        )
        items, _ = prepare_mux_track_items(
            config,
            settings.media_dir,
            settings.include_extra_subtitles,
            unknown_language,
            self.additional_mux_tracks,
            self.mux_track_language_overrides,
            self.mux_track_delay_overrides,
            self.mux_track_append_overrides,
        )
        apply_video_fps_override(items, settings.video_fps)
        ordered = apply_default_track_preferences(
            config,
            items,
            settings.audio_language_order,
            settings.subtitle_language_order,
        )
        ordered = apply_custom_track_order(ordered, self.mux_track_order_keys)
        manual_keys = {path_identity_key(track.path) for track in self.additional_mux_tracks}
        rows = []
        for item in ordered:
            key = path_identity_key(item.path)
            rows.append(
                MuxTrackWindowRow(
                    key=key,
                    path=item.path,
                    kind=track_type_label(item),
                    language=track_language_value(item) or MUX_UNKNOWN_LANGUAGE,
                    delay=normalise_mux_delay(str(item.track.get("delay") or "")),
                    delay_supported=track_type_value(item) in (0, 2),
                    append_paths=item.append_paths,
                    append_overridden=key in self.mux_track_append_overrides,
                    manual=key in manual_keys,
                    included=key not in self.mux_track_excluded_keys,
                )
            )
        for asset in self.additional_mux_assets:
            rows.append(
                MuxTrackWindowRow(
                    key=self.mux_window_row_key(asset.path, asset.kind, asset.target_name),
                    path=asset.path,
                    kind=self.mux_asset_kind_label(asset.kind),
                    language="",
                    delay="",
                    delay_supported=False,
                    asset_kind=asset.kind,
                    target_name=asset.target_name,
                    manual=True,
                    included=True,
                )
            )
        self.mux_track_source_keys = {row.key for row in rows if not row.manual}
        return rows

    def prepare_additional_mux_assets(self, settings: AppSettings) -> bool:
        for asset in self.additional_mux_assets:
            source = asset.path.expanduser()
            if source.exists():
                source = source.resolve()
            if not source.is_file():
                self.show_error(
                    self.tr("dialog_missing_info"),
                    self.tr("error_track_file_not_found", path=source),
                )
                return False
            target = settings.media_dir / asset.target_name
            try:
                if path_identity_key(source) == path_identity_key(target):
                    continue
            except OSError:
                pass
            if target.exists() and not self.ask_yes_no(
                self.tr("dialog_overwrite_title"),
                self.tr("dialog_overwrite_message", name=target.name),
            ):
                return False
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            except OSError as exc:
                self.show_error(
                    self.tr("dialog_error_title"),
                    self.tr("error_file_prepare_failed", name=target.name, error=exc),
                )
                return False
            self.queue_log(self.tr("log_manual_asset_ready", name=target.name))
        return True

    def mux_requires_tmdb(self, *, skip_track_window: bool = False) -> bool:
        if (
            skip_track_window
            and self.add_tracks_before_mux_var.get()
            and self.additional_mux_assets
            and not self.mux_track_download_missing_assets
        ):
            return False
        return bool(
            self.download_before_mux_var.get()
            or (
                skip_track_window
                and self.add_tracks_before_mux_var.get()
                and self.mux_track_download_missing_assets
            )
        )

    def mux_should_download_tmdb_assets(
        self,
        settings: AppSettings,
        *,
        skip_track_window: bool = False,
    ) -> bool:
        if skip_track_window and self.add_tracks_before_mux_var.get():
            if self.mux_track_download_missing_assets:
                return True
            if self.additional_mux_assets:
                return False
        return settings.download_before_mux

    def collect_extract_settings(self) -> tuple[Path, Path]:
        source_raw = self.extract_source_var.get().strip()
        if not source_raw:
            raise UserVisibleError(ui_text("error_source_mkv_not_selected"))
        source = Path(source_raw).expanduser()
        if not source.exists() or not source.is_file():
            raise UserVisibleError(ui_text("error_mkv_source_not_found", source=source))
        source = source.resolve()

        output_raw = self.extract_output_dir_var.get().strip()
        output_dir = Path(output_raw).expanduser() if output_raw else source.parent / f"{source.stem}_tracks"
        output_dir = output_dir.resolve()
        self.extract_output_dir_var.set(str(output_dir))
        return source, output_dir

    def collect_batch_folder_settings(
        self,
        *,
        require_mux: bool,
    ) -> tuple[AppSettings, Path, Path, list[BatchEpisodeTask]]:
        source_raw = self.extract_source_var.get().strip()
        if not source_raw:
            raise UserVisibleError(ui_text("error_source_folder_not_selected"))
        source_dir = Path(source_raw).expanduser()
        if not source_dir.exists() or not source_dir.is_dir():
            raise UserVisibleError(ui_text("error_source_folder_not_found", source=source_dir))
        source_dir = source_dir.resolve()

        sources = video_sources_in_folder(source_dir)
        if not sources:
            raise UserVisibleError(ui_text("error_batch_no_video_files"))

        template_raw = self.template_var.get().strip()
        template_path = Path(template_raw).expanduser() if template_raw else None
        if require_mux and template_path is not None and not template_path.exists():
            raise UserVisibleError(ui_text("error_template_missing", path=template_path))

        media_type = self.tmdb_media_type_from_display(self.media_type_display_var.get())
        if not media_type:
            media_type = self.media_type_var.get().strip()
        if media_type not in {"movie", "tv"}:
            raise UserVisibleError(ui_text("error_tmdb_media_type"))

        download_before_mux = self.download_before_mux_var.get()
        api_key = self.api_key_var.get().strip()
        tmdb_id = self.tmdb_id_var.get().strip()
        if require_mux and download_before_mux:
            if media_type != "tv":
                raise UserVisibleError(ui_text("error_batch_tmdb_tv_required"))
            if not api_key:
                raise UserVisibleError(ui_text("error_tmdb_artwork_api_required"))
            if tmdb_id and not tmdb_id.isdigit():
                raise UserVisibleError(ui_text("error_tmdb_id_numeric"))

        video_fps = self.video_fps_var.get().strip()
        normalize_video_fps(video_fps)

        output_raw = self.extract_output_dir_var.get().strip()
        extract_root = (
            Path(output_raw).expanduser()
            if output_raw
            else source_dir.parent / f"{source_dir.name}_tracks"
        ).resolve()
        self.extract_output_dir_var.set(str(extract_root))

        default_season = parse_season_number_from_text(source_dir.name)
        used_extract_dirs: set[str] = set()
        tasks: list[BatchEpisodeTask] = []
        for source in sources:
            episode_ref = episode_ref_from_path(source, default_season)
            if episode_ref is None:
                raise UserVisibleError(ui_text("error_episode_number_missing", name=source.name))

            base_name = safe_filename_stem(source.stem)
            candidate = extract_root / f"{base_name}_tracks"
            counter = 2
            while str(candidate).lower() in used_extract_dirs:
                candidate = extract_root / f"{base_name}_tracks_{counter}"
                counter += 1
            used_extract_dirs.add(str(candidate).lower())
            if require_mux and not candidate.exists():
                raise UserVisibleError(ui_text("error_batch_extract_dir_missing", path=candidate))
            tasks.append(BatchEpisodeTask(source, candidate, episode_ref))

        settings = AppSettings(
            template_path=template_path,
            media_dir=source_dir,
            output_path=source_dir / "output.mkv",
            output_name_extra=self.output_name_extra_var.get(),
            output_name_year=self.output_name_year_var.get(),
            api_key=api_key,
            tmdb_id=tmdb_id,
            media_type=media_type,
            image_language=self.language_var.get().strip() or "en",
            tag_language=self.tag_language_var.get().strip()
            or self.language_var.get().strip()
            or "en",
            mkv_title=self.title_var.get().strip(),
            video_fps=video_fps,
            audio_language_order=self.audio_language_order_var.get().strip(),
            subtitle_language_order=self.subtitle_language_order_var.get().strip(),
            include_extra_subtitles=self.include_extra_subs_var.get(),
            download_before_mux=download_before_mux,
            auto_chapters=self.auto_chapters_var.get(),
            auto_chapter_detect_intro=self.auto_chapter_detect_intro_var.get(),
            chapter_interval_minutes=self.chapter_interval_var.get().strip(),
            chapter_name=self.chapter_name_var.get().strip(),
            chapter_start_number=self.chapter_start_var.get().strip(),
            chapter_end_minutes=self.chapter_end_var.get().strip(),
        )
        return settings, source_dir, extract_root, tasks

    def collect_batch_subtitle_download_settings(
        self,
    ) -> tuple[AppSettings, Path, Path, list[BatchEpisodeTask]] | None:
        source_raw = self.extract_source_var.get().strip()
        if not source_raw:
            return None
        source_dir = Path(source_raw).expanduser()
        if not source_dir.exists() or not source_dir.is_dir():
            return None
        source_dir = source_dir.resolve()

        output_raw = self.extract_output_dir_var.get().strip()
        extract_root = (
            Path(output_raw).expanduser()
            if output_raw
            else source_dir.parent / f"{source_dir.name}_tracks"
        ).resolve()

        folder_raw = self.folder_var.get().strip()
        if folder_raw:
            media_dir = Path(folder_raw).expanduser().resolve()
            if media_dir != extract_root and not path_is_relative_to(media_dir, extract_root):
                return None

        return self.collect_batch_folder_settings(require_mux=True)

    def default_subtitle_download_language(self) -> str:
        current = self.subtitle_language_var.get().strip()
        if current:
            return normalise_subtitle_language(current)
        subtitle_order = parse_language_order(self.subtitle_language_order_var.get())
        if subtitle_order:
            return subtitle_order[0]
        for value in (self.tag_language_var.get(), self.language_var.get()):
            if value.strip():
                return normalise_subtitle_language(value)
        return "tr" if self.ui_language_var.get() == "tr" else "en"

    def subtitle_lookup_metadata(self, settings: AppSettings) -> SubtitleLookupMetadata:
        if not settings.api_key:
            return SubtitleLookupMetadata()
        try:
            metadata = subtitle_lookup_metadata_from_tmdb(settings)
        except UserVisibleError as exc:
            self.queue_log(self.tr("log_tmdb_id_auto_failed", error=exc))
            return SubtitleLookupMetadata()
        if metadata.tmdb_id:
            settings.tmdb_id = metadata.tmdb_id
            self.tmdb_id_var.set(metadata.tmdb_id)
        return metadata

    def apply_subtitle_lookup_metadata(
        self,
        target: SubtitleSearchTarget,
        metadata: SubtitleLookupMetadata,
    ) -> SubtitleSearchTarget:
        if not any((metadata.query, metadata.tmdb_id, metadata.imdb_id, metadata.year)):
            return target
        return replace(
            target,
            query=metadata.query or target.query,
            tmdb_id=metadata.tmdb_id or target.tmdb_id,
            imdb_id=metadata.imdb_id or target.imdb_id,
            year=metadata.year or target.year,
        )

    def subtitle_search_query_for_target(
        self,
        target: SubtitleSearchTarget,
        query_override: str,
    ) -> str:
        if not self.subtitle_batch_mode:
            return query_override or target.query
        if query_override and target.episode_ref is not None:
            return f"{query_override} {episode_code(target.episode_ref)}"
        return query_override or target.query

    def start_subtitle_search(self) -> None:
        api_key = self.subtitle_api_key_var.get().strip()
        if not api_key:
            self.show_error(
                self.tr("dialog_missing_info"),
                self.tr("error_subtitle_api_required"),
            )
            return
        targets = list(self.subtitle_targets)
        if not targets:
            self.show_error(
                self.tr("dialog_missing_info"),
                self.tr("error_track_folder_not_selected"),
            )
            return
        language = normalise_subtitle_language(self.subtitle_language_var.get())
        self.subtitle_language_var.set(language)
        query_override = self.subtitle_query_var.get().strip()
        self.subtitle_downloaded_paths = {}
        self.subtitle_status_var.set(self.tr("status_searching_subtitles"))
        self.save_preferences()

        def work() -> None:
            client = OpenSubtitlesClient(api_key)
            results: list[SubtitleResult] = []
            per_target_limit = 8 if len(targets) > 1 else 50
            for index, target in enumerate(targets):
                self.check_cancelled()
                query = self.subtitle_search_query_for_target(target, query_override)
                found = client.search(
                    target,
                    index,
                    language,
                    query,
                    limit=per_target_limit,
                )
                if not found:
                    self.queue_log(
                        self.tr(
                            "log_subtitle_no_result_for_target",
                            target=subtitle_target_label(target),
                        )
                    )
                results.extend(found)
            self.log_queue.put(("set_subtitle_results", results))
            if not results:
                self.log_queue.put(("set_subtitle_status", ui_text("label_subtitle_status_no_results")))
                self.queue_log(self.tr("error_subtitle_no_results"))
                return
            self.log_queue.put(("set_subtitle_status", ui_text("log_subtitle_results_found", count=len(results))))
            self.queue_log(self.tr("log_subtitle_results_found", count=len(results)))

        self.run_background(work, self.tr("status_searching_subtitles"))

    def subtitle_download_status(self, result_key: str) -> str:
        return (
            self.tr("value_subtitle_downloaded")
            if result_key in self.subtitle_downloaded_paths
            else ""
        )

    def not_downloaded_subtitle_results(
        self,
        results: list[SubtitleResult],
    ) -> list[SubtitleResult]:
        return [
            result
            for result in results
            if result.key not in self.subtitle_downloaded_paths
        ]

    def best_subtitle_results(self) -> list[SubtitleResult]:
        selected: dict[int, SubtitleResult] = {}
        for result in self.subtitle_results.values():
            if result.key in self.subtitle_downloaded_paths:
                continue
            selected.setdefault(result.target_index, result)
        return list(selected.values())

    def start_subtitle_download_selected(self) -> None:
        self.start_subtitle_download(self.selected_subtitle_results())

    def start_subtitle_download_best(self) -> None:
        self.start_subtitle_download(self.best_subtitle_results())

    def start_subtitle_download(self, results: list[SubtitleResult]) -> None:
        if not results:
            self.show_error(
                self.tr("dialog_missing_info"),
                self.tr("error_subtitle_no_selection"),
            )
            return
        results = self.not_downloaded_subtitle_results(results)
        if not results:
            self.show_info(
                self.tr("dialog_missing_info"),
                self.tr("error_subtitle_all_selected_downloaded"),
            )
            return
        api_key = self.subtitle_api_key_var.get().strip()
        username = self.subtitle_username_var.get().strip()
        password = self.subtitle_password_var.get()
        if not api_key:
            self.show_error(
                self.tr("dialog_missing_info"),
                self.tr("error_subtitle_api_required"),
            )
            return
        if not username or not password:
            self.show_error(
                self.tr("dialog_missing_info"),
                self.tr("error_subtitle_credentials_required"),
            )
            return
        try:
            normalize_video_fps(self.video_fps_var.get().strip())
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return
        out_fps = parse_fps_number(self.video_fps_var.get())
        self.save_preferences()

        def work() -> None:
            client = OpenSubtitlesClient(api_key, username, password)
            token, base_url = client.login()
            count = 0
            for result in results:
                self.check_cancelled()
                if result.key in self.subtitle_downloaded_paths:
                    continue
                target = self.subtitle_targets[result.target_index]
                destination = download_subtitle_result(
                    client,
                    result,
                    target,
                    token,
                    base_url,
                    out_fps,
                )
                count += 1
                self.queue_log(self.tr("log_subtitle_downloaded", path=destination))
                self.log_queue.put(("mark_subtitle_downloaded", (result.key, destination)))
            if len(self.subtitle_targets) > 1:
                self.queue_log(self.tr("log_batch_subtitles_complete", count=count))

        self.run_background(work, self.tr("status_downloading_subtitles"))

    def start_check_app_update(self) -> None:
        if self.app_update_thread is not None and self.app_update_thread.is_alive():
            return

        def work() -> None:
            try:
                release = latest_app_release()
                if app_release_is_newer(release):
                    self.log_queue.put(("app_update_available", release))
            except Exception:
                return

        self.app_update_thread = threading.Thread(target=work, daemon=True)
        self.app_update_thread.start()

    def start_update_third_party(self) -> None:
        groups = (
            ("mkvtoolnix", "MKVToolNix"),
            ("ffmpeg", "FFmpeg"),
        )

        def work() -> None:
            for group, name in groups:
                self.queue_log(self.tr("log_third_party_checking", name=name))
                result = ensure_third_party_group(group, force_check=True)
                version = str(result.get("version") or "installed")
                if result.get("existing_used"):
                    self.queue_log(
                        self.tr(
                            "log_third_party_existing_used",
                            name=name,
                            version=version,
                        )
                    )
                elif result.get("changed"):
                    self.queue_log(
                        self.tr("log_third_party_updated", name=name, version=version)
                    )
                else:
                    self.queue_log(
                        self.tr("log_third_party_current", name=name, version=version)
                    )
            self.queue_log(self.tr("log_third_party_complete"))

        self.run_background(work, self.tr("status_updating_third_party"))

    def start_tmdb_name_search(self) -> None:
        query = self.tmdb_search_query_var.get().strip()
        api_key = self.api_key_var.get().strip()
        if not api_key:
            self.show_error(self.tr("dialog_missing_info"), self.tr("error_tmdb_api_empty"))
            return
        if not query:
            self.show_error(
                self.tr("dialog_missing_info"),
                self.tr("error_tmdb_search_query_empty"),
            )
            return

        language = detail_language(self.ui_language_var.get())
        self.tmdb_search_status_var.set(self.tr("label_tmdb_search_status_searching"))

        def work() -> None:
            results = TMDBClient(api_key).search_multi(query, language)
            self.log_queue.put(("set_tmdb_search_results", results))
            if results:
                status = self.tr("label_tmdb_search_status_results", count=len(results))
            else:
                status = self.tr("label_tmdb_search_status_no_results")
            self.log_queue.put(("set_tmdb_search_status", status))

        self.run_background(work, self.tr("label_tmdb_search_status_searching"))

    def start_find_tmdb_id(self, auto: bool = False) -> None:
        try:
            settings = self.collect_settings()
            if not settings.api_key:
                if not auto:
                    raise UserVisibleError(ui_text("error_tmdb_api_empty"))
                return
            self.save_preferences()
        except UserVisibleError as exc:
            if not auto:
                self.show_error(self.tr("dialog_missing_info"), str(exc))
            return

        # ID Bul her çalıştığında FPS alanı bu klasörün videosuna göre yenilenmeli.
        # Eski klasörden kalan FPS değeri burada referans alınmaz; önce alan temizlenir,
        # sonra mevcut medya dosyalarından bulunan yeni FPS değeri UI'ye yazılır.
        self.video_fps_var.set("")
        settings.video_fps = ""

        def work() -> None:
            try:
                tmdb_id, title, found_year, query = find_tmdb_match_from_folder(settings)
            except UserVisibleError as exc:
                if auto:
                    self.queue_log(self.tr("log_tmdb_id_auto_failed", error=exc))
                    return
                raise
            self.log_queue.put(("set_tmdb_id", tmdb_id))
            fps = detect_first_video_fps_from_media_dir(settings.media_dir)
            self.log_queue.put(("set_video_fps", fps))
            if fps:
                settings.video_fps = fps
                self.queue_log(self.tr("log_video_fps_detected", fps=fps))
            episode_ref = episode_ref_from_settings(settings)
            image_title = tmdb_output_title_for_language(
                settings,
                tmdb_id,
                settings.image_language,
                episode_ref,
            )
            if image_title:
                output_path = output_path_with_optional_year(
                    tmdb_output_path(settings.media_dir, image_title),
                    enabled=settings.output_name_year,
                    media_type=settings.media_type,
                    media_dir=settings.media_dir,
                    extra=settings.output_name_extra,
                    tmdb_year=found_year,
                )
                self.log_queue.put(("set_output", str(output_path)))
                self.queue_log(
                    self.tr("log_output_from_artwork_language", name=output_path.name)
                )
            tag_title = tmdb_output_title_for_language(
                settings,
                tmdb_id,
                settings.tag_language,
                episode_ref,
            )
            if tag_title and (not auto or not settings.mkv_title):
                self.log_queue.put(("set_title", tag_title))
                self.queue_log(self.tr("log_title_from_tag_language", title=tag_title))
            year_text = f" ({found_year})" if found_year else ""
            title_text = image_title or title or query
            self.queue_log(
                self.tr(
                    "log_tmdb_id_found",
                    tmdb_id=tmdb_id,
                    title=title_text,
                    year_text=year_text,
                )
            )

        self.run_background(work, self.tr("status_finding_tmdb"))

    def collect_batch_asset_download_settings(
        self,
    ) -> tuple[AppSettings, Path, Path, list[BatchEpisodeTask]] | None:
        source_raw = self.extract_source_var.get().strip()
        if not source_raw:
            return None
        source_dir = Path(source_raw).expanduser()
        if not source_dir.exists() or not source_dir.is_dir():
            return None
        source_dir = source_dir.resolve()

        output_raw = self.extract_output_dir_var.get().strip()
        extract_root = (
            Path(output_raw).expanduser()
            if output_raw
            else source_dir.parent / f"{source_dir.name}_tracks"
        ).resolve()

        folder_raw = self.folder_var.get().strip()
        if folder_raw:
            media_dir = Path(folder_raw).expanduser().resolve()
            if media_dir != extract_root and not path_is_relative_to(media_dir, extract_root):
                return None

        settings, source_dir, extract_root, tasks = self.collect_batch_folder_settings(
            require_mux=True
        )
        if settings.media_type != "tv":
            raise UserVisibleError(ui_text("error_batch_tmdb_tv_required"))
        if not settings.api_key:
            raise UserVisibleError(ui_text("error_tmdb_artwork_api_required"))
        if not settings.tmdb_id:
            raise UserVisibleError(ui_text("error_tmdb_id_empty"))
        if not settings.tmdb_id.isdigit():
            raise UserVisibleError(ui_text("error_tmdb_id_numeric"))
        return settings, source_dir, extract_root, tasks

    def start_download(self) -> None:
        try:
            batch_settings = self.collect_batch_asset_download_settings()
            if batch_settings is None:
                settings = self.collect_settings(require_tmdb=True)
            else:
                settings, source_dir, _extract_root, tasks = batch_settings
            self.save_preferences()
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return

        if batch_settings is not None:
            def batch_work() -> None:
                for index, task in enumerate(tasks, start=1):
                    self.check_cancelled()
                    self.queue_log(
                        self.tr(
                            "log_batch_episode",
                            index=index,
                            count=len(tasks),
                            name=task.source.name,
                        )
                    )
                    self.queue_log(self.tr("log_batch_extract_dir", path=task.extract_dir))
                    episode_settings = copy.copy(settings)
                    episode_settings.media_dir = task.extract_dir
                    download_tmdb_assets(
                        episode_settings,
                        self.queue_log,
                        episode_ref=task.episode_ref,
                        replace_existing=True,
                    )
                self.queue_log(self.tr("log_batch_assets_complete", count=len(tasks)))

            self.run_background(batch_work, self.tr("status_downloading_assets"))
            return

        def work() -> None:
            title, tmdb_year = download_tmdb_assets(
                settings,
                self.queue_log,
                replace_existing=True,
            )
            if title:
                output_path = output_path_with_optional_year(
                    tmdb_output_path(settings.media_dir, title),
                    enabled=settings.output_name_year,
                    media_type=settings.media_type,
                    media_dir=settings.media_dir,
                    extra=settings.output_name_extra,
                    tmdb_year=tmdb_year,
                )
                self.log_queue.put(("set_output", str(output_path)))
                self.queue_log(
                    self.tr("log_output_from_artwork_language", name=output_path.name)
                )

        self.run_background(work, self.tr("status_downloading_assets"))

    def start_write_config(self) -> None:
        try:
            settings = self.collect_settings()
            auto_chapter_end = self.chapter_end_needs_auto_detection(settings.chapter_end_minutes)
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return

        def work() -> None:
            config = load_or_create_template_config(settings.template_path, settings.media_dir)
            (
                additional_tracks,
                track_order_keys,
                language_overrides,
                delay_overrides,
                append_overrides,
                excluded_track_keys,
            ) = self.mux_track_customizations()
            if settings.auto_chapters and auto_chapter_end:
                self.queue_log(self.tr("log_detecting_chapter_end"))
                chapter_end = detect_chapter_end_minutes_for_media_dir(
                    config,
                    settings.media_dir,
                    settings.include_extra_subtitles,
                    settings.tag_language,
                    cancel_event=self.cancel_event,
                    register_process=self.register_active_process,
                    unregister_process=self.unregister_active_process,
                )
                if chapter_end:
                    settings.chapter_end_minutes = chapter_end
                    self.log_queue.put(("set_chapter_end_auto", chapter_end))
            if settings.auto_chapters and settings.auto_chapter_detect_intro:
                self.queue_log(self.tr("log_detecting_intro_end"))
            settings.output_path.parent.mkdir(parents=True, exist_ok=True)
            generated = write_generated_config(
                config,
                settings.media_dir,
                settings.output_path,
                settings.mkv_title,
                settings.include_extra_subtitles,
                settings.video_fps,
                self.chapter_options_from_settings(settings),
                settings.audio_language_order,
                settings.subtitle_language_order,
                settings.tag_language,
                additional_tracks,
                track_order_keys,
                language_overrides,
                delay_overrides,
                append_overrides,
                excluded_track_keys,
            )
            self.queue_log(self.tr("log_config_written", path=generated))

        self.run_background(work, self.tr("status_writing_config"))

    def start_mux(self, *, skip_track_window: bool = False) -> None:
        if (
            self.worker is not None
            and self.worker.is_alive()
            and self.current_operation == "mux"
        ):
            self.cancel_current_operation()
            return

        try:
            settings = self.collect_settings(
                require_tmdb=self.mux_requires_tmdb(skip_track_window=skip_track_window)
            )
            settings.download_before_mux = self.mux_should_download_tmdb_assets(
                settings,
                skip_track_window=skip_track_window,
            )
            auto_chapter_end = self.chapter_end_needs_auto_detection(settings.chapter_end_minutes)
            self.save_preferences()
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return

        if self.add_tracks_before_mux_var.get() and not skip_track_window:
            self.open_mux_tracks_window(settings)
            return

        overwrite_existing = False
        if settings.output_path.exists():
            overwrite_existing = self.ask_yes_no(
                self.tr("dialog_overwrite_title"),
                self.tr("dialog_overwrite_message", name=settings.output_path.name),
            )
            if not overwrite_existing:
                return

        def work() -> None:
            config = load_or_create_template_config(settings.template_path, settings.media_dir)
            (
                additional_tracks,
                track_order_keys,
                language_overrides,
                delay_overrides,
                append_overrides,
                excluded_track_keys,
            ) = self.mux_track_customizations()
            settings.output_path.parent.mkdir(parents=True, exist_ok=True)

            if settings.download_before_mux:
                title, tmdb_year = download_tmdb_assets(settings, self.queue_log)
                if title:
                    settings.output_path = output_path_with_optional_year(
                        tmdb_output_path(settings.media_dir, title),
                        enabled=settings.output_name_year,
                        media_type=settings.media_type,
                        media_dir=settings.media_dir,
                        extra=settings.output_name_extra,
                        tmdb_year=tmdb_year,
                    )
                    settings.output_path.parent.mkdir(parents=True, exist_ok=True)
                    self.log_queue.put(("set_output", str(settings.output_path)))
                    self.queue_log(
                        self.tr(
                            "log_output_from_artwork_language",
                            name=settings.output_path.name,
                        )
                    )

            if settings.output_path.exists():
                if not overwrite_existing:
                    raise UserVisibleError(
                        ui_text(
                            "error_output_exists_choose",
                            name=settings.output_path.name,
                        )
                    )
                try:
                    settings.output_path.unlink()
                except OSError as exc:
                    raise UserVisibleError(
                        ui_text(
                            "error_output_delete_failed",
                            name=settings.output_path.name,
                            error=exc,
                        )
                    ) from exc

            if settings.auto_chapters and auto_chapter_end:
                self.queue_log(self.tr("log_detecting_chapter_end"))
                chapter_end = detect_chapter_end_minutes_for_media_dir(
                    config,
                    settings.media_dir,
                    settings.include_extra_subtitles,
                    settings.tag_language,
                    cancel_event=self.cancel_event,
                    register_process=self.register_active_process,
                    unregister_process=self.unregister_active_process,
                )
                if chapter_end:
                    settings.chapter_end_minutes = chapter_end
                    self.log_queue.put(("set_chapter_end_auto", chapter_end))

            if settings.auto_chapters and settings.auto_chapter_detect_intro:
                self.queue_log(self.tr("log_detecting_intro_end"))
            args, missing_optional = build_mkvmerge_args(
                config,
                settings.media_dir,
                settings.output_path,
                settings.mkv_title,
                settings.include_extra_subtitles,
                settings.video_fps,
                self.chapter_options_from_settings(settings),
                settings.audio_language_order,
                settings.subtitle_language_order,
                settings.tag_language,
                additional_tracks,
                track_order_keys,
                language_overrides,
                delay_overrides,
                append_overrides,
                excluded_track_keys,
                cancel_event=self.cancel_event,
                register_process=self.register_active_process,
                unregister_process=self.unregister_active_process,
            )

            self.check_cancelled()

            generated = write_generated_config(
                config,
                settings.media_dir,
                settings.output_path,
                settings.mkv_title,
                settings.include_extra_subtitles,
                settings.video_fps,
                self.chapter_options_from_settings(settings),
                settings.audio_language_order,
                settings.subtitle_language_order,
                settings.tag_language,
                additional_tracks,
                track_order_keys,
                language_overrides,
                delay_overrides,
                append_overrides,
                excluded_track_keys,
            )
            self.queue_log(self.tr("log_config_written", path=generated))
            if missing_optional:
                self.queue_log(
                    self.tr(
                        "log_skipped_optional_tracks",
                        items=", ".join(missing_optional),
                    )
                )
            self.queue_log(self.tr("log_mkvmerge_command"))
            self.queue_log(command_preview(args))

            process = subprocess.Popen(
                args,
                cwd=str(settings.media_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                **subprocess_common_kwargs(),
                bufsize=1,
                env=third_party_subprocess_env(),
                executable=third_party_subprocess_executable(args),
            )
            self.register_active_process(process)
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    if self.cancel_event.is_set():
                        terminate_process(process)
                        break
                    self.queue_log(line.rstrip())
                if self.cancel_event.is_set():
                    terminate_process(process)
                    raise OperationCancelled(self.tr("log_operation_cancelled"))
                return_code = process.wait()
            finally:
                self.unregister_active_process(process)
            if return_code > 1:
                raise UserVisibleError(ui_text("error_mkvmerge_exit", code=return_code))
            if return_code == 1:
                self.queue_log(self.tr("log_mkvmerge_warnings"))
            self.queue_log(self.tr("log_mkv_created", path=settings.output_path))

        self.run_background(work, self.tr("status_creating_mkv"), operation="mux")

    def start_batch_extract_folder(self) -> None:
        if (
            self.worker is not None
            and self.worker.is_alive()
            and self.current_operation == "mux"
        ):
            self.cancel_current_operation()
            return

        try:
            settings, source_dir, extract_root, tasks = self.collect_batch_folder_settings(
                require_mux=False
            )
            self.save_preferences()
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return

        def work() -> None:
            extract_root.mkdir(parents=True, exist_ok=True)
            first_fps = ""

            for index, task in enumerate(tasks, start=1):
                self.check_cancelled()
                self.queue_log(
                    self.tr(
                        "log_batch_episode",
                        index=index,
                        count=len(tasks),
                        name=task.source.name,
                    )
                )
                self.queue_log(self.tr("log_batch_extract_dir", path=task.extract_dir))

                payload = identify_mkv(task.source)
                extract_items = build_extract_items(payload, task.source)
                fps = settings.video_fps or first_video_fps_from_items(extract_items)
                if index == 1:
                    first_fps = fps
                    chapter_end = chapter_end_minutes_from_duration_seconds(
                        duration_seconds_from_identify_payload(payload)
                    )
                    if chapter_end:
                        self.log_queue.put(("set_chapter_end_auto", chapter_end))
                if fps and not settings.video_fps:
                    self.queue_log(self.tr("log_video_fps_detected", fps=fps))

                args, command_log_key, exit_error_key = build_extract_command(
                    task.source,
                    task.extract_dir,
                    extract_items,
                )
                self.queue_log(self.tr(command_log_key))
                self.queue_log(command_preview(args))
                extract_warning_key = (
                    "log_mkvextract_warnings"
                    if command_log_key == "log_mkvextract_command"
                    else None
                )
                self.run_cancellable_tool_process(
                    args,
                    task.extract_dir,
                    exit_error_key,
                    extract_warning_key,
                )

            first_task = tasks[0]
            first_title = batch_episode_preview_title(source_dir, first_task)
            self.log_queue.put(("set_folder", str(first_task.extract_dir)))
            self.log_queue.put(
                ("set_output", str(batch_episode_output_path(source_dir, first_task)))
            )
            self.log_queue.put(("set_title", first_title))
            if first_fps:
                self.log_queue.put(("set_video_fps", first_fps))
            self.queue_log(self.tr("log_batch_extract_complete", count=len(tasks)))

        self.run_background(
            work,
            self.tr("status_batch_extract_folder"),
            operation="mux",
        )

    def start_batch_mux_folder(self) -> None:
        if (
            self.worker is not None
            and self.worker.is_alive()
            and self.current_operation == "mux"
        ):
            self.cancel_current_operation()
            return

        try:
            settings, source_dir, _extract_root, tasks = self.collect_batch_folder_settings(
                require_mux=True
            )
            auto_chapter_end = self.chapter_end_needs_auto_detection(settings.chapter_end_minutes)
            self.save_preferences()
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return

        def work() -> None:
            if settings.download_before_mux and not settings.tmdb_id:
                self.queue_log(self.tr("status_finding_tmdb"))
                tmdb_id, title, found_year, query = find_tmdb_match_from_folder(settings)
                settings.tmdb_id = tmdb_id
                self.log_queue.put(("set_tmdb_id", tmdb_id))
                year_text = f" ({found_year})" if found_year else ""
                self.queue_log(
                    self.tr(
                        "log_tmdb_id_found",
                        tmdb_id=tmdb_id,
                        title=title or query,
                        year_text=year_text,
                    )
                )

            created_outputs: list[tuple[Path, EpisodeRef]] = []
            first_ref = tasks[0].episode_ref
            first_default_mux_title = ""
            for index, task in enumerate(tasks, start=1):
                self.check_cancelled()
                self.queue_log(
                    self.tr(
                        "log_batch_episode",
                        index=index,
                        count=len(tasks),
                        name=task.source.name,
                    )
                )
                self.queue_log(self.tr("log_batch_extract_dir", path=task.extract_dir))

                # Batch mux must use each episode folder's own video FPS.
                # The UI value is only a fallback when the episode FPS cannot be detected.
                detected_fps = detect_first_video_fps_from_media_dir(task.extract_dir)
                fps = detected_fps or settings.video_fps
                if detected_fps:
                    self.queue_log(self.tr("log_video_fps_detected", fps=detected_fps))

                episode_settings = copy.copy(settings)
                episode_settings.media_dir = task.extract_dir
                episode_settings.output_path = (
                    task.extract_dir / f"{safe_filename_stem(task.source.stem)}.mkv"
                )
                episode_settings.video_fps = fps

                default_mux_title = batch_episode_preview_title(source_dir, task)
                if (
                    episode_settings.api_key
                    and episode_settings.tmdb_id
                    and episode_settings.media_type == "tv"
                ):
                    default_mux_title = tmdb_output_title_for_language(
                        episode_settings,
                        episode_settings.tmdb_id,
                        episode_settings.tag_language,
                        task.episode_ref,
                    )

                if episode_settings.download_before_mux:
                    output_title, _tmdb_year = download_tmdb_assets(
                        episode_settings,
                        self.queue_log,
                        episode_ref=task.episode_ref,
                    )
                    if output_title:
                        episode_settings.output_path = tmdb_output_path(
                            episode_settings.media_dir,
                            output_title,
                        )
                elif default_mux_title:
                    episode_settings.output_path = tmdb_output_path(
                        episode_settings.media_dir,
                        default_mux_title,
                    )
                else:
                    episode_settings.output_path = batch_episode_output_path(source_dir, task)
                episode_settings.output_path = output_path_with_name_extra(
                    episode_settings.output_path,
                    episode_settings.output_name_extra,
                )

                if index == 1:
                    first_default_mux_title = default_mux_title
                mux_title = batch_mkv_title_for_episode(
                    settings.mkv_title,
                    default_mux_title,
                    first_default_mux_title,
                    first_ref,
                    task.episode_ref,
                )

                if episode_settings.output_path.exists():
                    raise UserVisibleError(
                        ui_text(
                            "error_output_exists_choose",
                            name=episode_settings.output_path.name,
                        )
                    )

                config = load_or_create_template_config(
                    episode_settings.template_path,
                    episode_settings.media_dir,
                )
                if episode_settings.auto_chapters and auto_chapter_end:
                    self.queue_log(self.tr("log_detecting_chapter_end"))
                    episode_settings.chapter_end_minutes = ""
                    chapter_end = detect_chapter_end_minutes_for_source(task.source)
                    if not chapter_end:
                        chapter_end = detect_chapter_end_minutes_for_media_dir(
                            config,
                            episode_settings.media_dir,
                            episode_settings.include_extra_subtitles,
                            episode_settings.tag_language,
                            cancel_event=self.cancel_event,
                            register_process=self.register_active_process,
                            unregister_process=self.unregister_active_process,
                        )
                    if chapter_end:
                        episode_settings.chapter_end_minutes = chapter_end
                        if index == 1:
                            self.log_queue.put(("set_chapter_end_auto", chapter_end))
                episode_settings.output_path.parent.mkdir(parents=True, exist_ok=True)
                if episode_settings.auto_chapters and episode_settings.auto_chapter_detect_intro:
                    self.queue_log(self.tr("log_detecting_intro_end"))
                episode_chapter_options = self.chapter_options_from_settings(episode_settings)
                episode_chapter_options.analysis_source = task.source
                mux_args, missing_optional = build_mkvmerge_args(
                    config,
                    episode_settings.media_dir,
                    episode_settings.output_path,
                    mux_title,
                    episode_settings.include_extra_subtitles,
                    episode_settings.video_fps,
                    episode_chapter_options,
                    episode_settings.audio_language_order,
                    episode_settings.subtitle_language_order,
                    episode_settings.tag_language,
                    cancel_event=self.cancel_event,
                    register_process=self.register_active_process,
                    unregister_process=self.unregister_active_process,
                )

                generated = write_generated_config(
                    config,
                    episode_settings.media_dir,
                    episode_settings.output_path,
                    mux_title,
                    episode_settings.include_extra_subtitles,
                    episode_settings.video_fps,
                    episode_chapter_options,
                    episode_settings.audio_language_order,
                    episode_settings.subtitle_language_order,
                    episode_settings.tag_language,
                )
                self.queue_log(self.tr("log_config_written", path=generated))
                if missing_optional:
                    self.queue_log(
                        self.tr(
                            "log_skipped_optional_tracks",
                            items=", ".join(missing_optional),
                        )
                    )
                self.queue_log(self.tr("log_mkvmerge_command"))
                self.queue_log(command_preview(mux_args))
                self.run_cancellable_tool_process(
                    mux_args,
                    episode_settings.media_dir,
                    "error_mkvmerge_exit",
                    "log_mkvmerge_warnings",
                )
                self.queue_log(self.tr("log_mkv_created", path=episode_settings.output_path))
                created_outputs.append((episode_settings.output_path, task.episode_ref))

            season_dirs: dict[int, Path] = {}
            move_plan: list[tuple[Path, Path]] = []
            used_targets: set[str] = set()
            for output_path, episode_ref in created_outputs:
                final_dir = season_dirs.get(episode_ref.season)
                if final_dir is None:
                    final_dir = tmdb_season_folder_path(source_dir, settings, episode_ref.season)
                    season_dirs[episode_ref.season] = final_dir
                target = final_dir / output_path.name
                target_key = str(target).lower()
                if target_key in used_targets or target.exists():
                    raise UserVisibleError(ui_text("error_output_exists_choose", name=target.name))
                used_targets.add(target_key)
                move_plan.append((output_path, target))

            for final_dir in season_dirs.values():
                final_dir.mkdir(parents=True, exist_ok=True)
                self.queue_log(self.tr("log_batch_final_folder", path=final_dir))

            for output_path, target in move_plan:
                shutil.move(str(output_path), str(target))
                self.queue_log(self.tr("log_batch_moved", path=target))

            self.queue_log(self.tr("log_batch_mux_complete", count=len(move_plan)))

        self.run_background(
            work,
            self.tr("status_batch_mux_folder"),
            operation="mux",
        )

    def start_scan_extract(self) -> None:
        try:
            source, output_dir = self.collect_extract_settings()
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return
        self.ensure_extract_window()

        def work() -> None:
            payload = identify_mkv(source)
            items = build_extract_items(payload, source)
            self.log_queue.put(("set_extract_items", items))
            self.log_queue.put(("set_extract_dir", str(output_dir)))
            chapter_end = chapter_end_minutes_from_duration_seconds(
                duration_seconds_from_identify_payload(payload)
            )
            if chapter_end:
                self.log_queue.put(("set_chapter_end_auto", chapter_end))
            fps = first_video_fps_from_identify_payload(payload, source) or first_video_fps_from_items(items)
            if fps:
                self.log_queue.put(("set_video_fps", fps))
                self.queue_log(self.tr("log_video_fps_detected", fps=fps))
            self.queue_log(self.tr("log_mkv_items_found", count=len(items)))
            for item in items:
                self.queue_log(f"  {item.label} -> {item.output_name}")

        self.run_background(work, self.tr("status_scanning_mkv"))

    def start_extract(self) -> None:
        try:
            source, output_dir = self.collect_extract_settings()
        except UserVisibleError as exc:
            self.show_error(self.tr("dialog_missing_info"), str(exc))
            return

        if not self.extract_items:
            self.show_error(
                self.tr("dialog_missing_info"),
                self.tr("error_scan_extract_first"),
            )
            return

        for item_key, variable in self.extract_language_vars.items():
            item = self.extract_items.get(item_key)
            if item is not None:
                item.language_override = variable.get()
        self.refresh_extract_output_names()

        items = [copy.deepcopy(item) for item in self.extract_items.values() if item.selected]
        if not items:
            self.show_error(
                self.tr("dialog_missing_info"),
                self.tr("error_extract_none_selected"),
            )
            return

        def work() -> None:
            args, command_log_key, exit_error_key = build_extract_command(source, output_dir, items)
            self.queue_log(self.tr(command_log_key))
            self.queue_log(command_preview(args))
            process = subprocess.Popen(
                args,
                cwd=str(output_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                **subprocess_common_kwargs(),
                bufsize=1,
                env=third_party_subprocess_env(),
                executable=third_party_subprocess_executable(args),
            )
            assert process.stdout is not None
            for line in process.stdout:
                self.queue_log(line.rstrip())
            return_code = process.wait()
            if return_code > 1:
                raise UserVisibleError(ui_text(exit_error_key, code=return_code))
            if return_code == 1:
                self.queue_log(self.tr("log_mkvextract_warnings"))

            fps = first_video_fps_from_identify_payload(identify_mkv(source), source) or first_video_fps_from_items(items)
            if fps:
                self.log_queue.put(("set_video_fps", fps))
            self.log_queue.put(("set_folder", str(output_dir)))
            self.queue_log(self.tr("log_tracks_extracted", path=output_dir))
            self.queue_log(self.tr("log_folder_set_for_mux"))
            self.log_queue.put(("close_extract", True))

        self.run_background(work, self.tr("status_extracting_tracks"))

    def register_active_process(self, process: subprocess.Popen[Any]) -> None:
        with self.active_processes_lock:
            self.active_processes.add(process)

    def unregister_active_process(self, process: subprocess.Popen[Any]) -> None:
        with self.active_processes_lock:
            self.active_processes.discard(process)

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise OperationCancelled(self.tr("log_operation_cancelled"))

    def cancel_current_operation(self) -> None:
        if self.cancel_event.is_set():
            return
        self.cancel_event.set()
        self.progress_status_var.set(self.tr("status_cancelling"))
        self.queue_log(self.tr("status_cancelling"))
        with self.active_processes_lock:
            processes = list(self.active_processes)
        for process in processes:
            terminate_process(process)

    def run_cancellable_tool_process(
        self,
        args: list[str],
        cwd: Path,
        exit_error_key: str,
        warning_key: str | None = None,
    ) -> int:
        process = subprocess.Popen(
            args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **subprocess_common_kwargs(),
            bufsize=1,
            env=third_party_subprocess_env(),
            executable=third_party_subprocess_executable(args),
        )
        self.register_active_process(process)
        try:
            assert process.stdout is not None
            for line in process.stdout:
                if self.cancel_event.is_set():
                    terminate_process(process)
                    break
                self.queue_log(line.rstrip())
            if self.cancel_event.is_set():
                terminate_process(process)
                raise OperationCancelled(self.tr("log_operation_cancelled"))
            return_code = process.wait()
        finally:
            self.unregister_active_process(process)

        if return_code > 1 or (return_code == 1 and not warning_key):
            raise UserVisibleError(ui_text(exit_error_key, code=return_code))
        if return_code == 1 and warning_key:
            self.queue_log(self.tr(warning_key))
        return return_code

    def run_background(
        self,
        work: Callable[[], Any],
        status: str | None = None,
        operation: str | None = None,
    ) -> bool:
        if self.worker and self.worker.is_alive():
            self.show_info(
                self.tr("dialog_in_progress_title"),
                self.tr("dialog_in_progress_message"),
            )
            return False

        self.cancel_event.clear()
        self.current_operation = operation
        self.set_busy(True, status or self.tr("status_processing"))

        def wrapped() -> None:
            try:
                work()
            except OperationCancelled:
                self.queue_log(self.tr("log_operation_cancelled"))
            except UserVisibleError as exc:
                self.queue_error(str(exc))
            except Exception as exc:
                self.queue_error(ui_text("error_unexpected", error=exc))
            finally:
                self.cancel_event.clear()
                self.current_operation = None
                self.log_queue.put(("busy", False))

        self.worker = threading.Thread(target=wrapped, daemon=True)
        self.worker.start()
        return True

    def short_status_message(self, message: str) -> str:
        value = re.sub(r"\s+", " ", message).strip()
        if len(value) > 150:
            return value[:147].rstrip() + "..."
        return value

    def queue_log(self, message: str) -> None:
        self.log_queue.put(("log", message))

    def queue_error(self, message: str) -> None:
        self.log_queue.put(("error", message))
