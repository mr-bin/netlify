(function () {
    var triggers = Array.prototype.slice.call(document.querySelectorAll(".cta-reveal-trigger"));
    triggers.forEach(function (btn) {
        var panel = document.getElementById(btn.getAttribute("aria-controls"));
        if (!panel) return;
        btn.addEventListener("click", function () {
            var isOpen = panel.classList.toggle("is-open");
            btn.setAttribute("aria-expanded", isOpen ? "true" : "false");
        });
    });
})();

(function () {
    var toggle = document.getElementById("navToggle");
    var nav = document.getElementById("topNav");
    if (!toggle || !nav) return;

    function closeNav() {
        nav.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
    }

    toggle.addEventListener("click", function () {
        var isOpen = nav.classList.toggle("is-open");
        toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });

    nav.querySelectorAll("a").forEach(function (a) {
        a.addEventListener("click", closeNav);
    });

    document.addEventListener("click", function (e) {
        if (!nav.classList.contains("is-open")) return;
        if (nav.contains(e.target) || toggle.contains(e.target)) return;
        closeNav();
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") closeNav();
    });
})();

(function () {
    function setupExpandable(toggleId) {
        var toggle = document.getElementById(toggleId);
        if (!toggle) return;
        var container = document.getElementById(toggle.getAttribute("aria-controls"));
        if (!container) return;
        var labelMore = toggle.getAttribute("data-label-more") || toggle.textContent.trim();
        var labelLess = toggle.getAttribute("data-label-less") || "Свернуть";

        toggle.addEventListener("click", function () {
            var isOpen = container.classList.toggle("is-expanded");
            toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
            toggle.textContent = isOpen ? labelLess : labelMore;
        });
    }

    setupExpandable("eduTimelineToggle");
    setupExpandable("eduDocsToggle");
})();

(function () {
    var thumbs = Array.prototype.slice.call(document.querySelectorAll(".doc-thumb"));
    if (!thumbs.length) return;

    var lightbox = document.getElementById("lightbox");
    var lightboxImg = document.getElementById("lightbox-img");
    var btnClose = document.getElementById("lightbox-close");
    var btnPrev = document.getElementById("lightbox-prev");
    var btnNext = document.getElementById("lightbox-next");
    var current = 0;

    function open(index) {
        current = index;
        lightboxImg.src = thumbs[current].getAttribute("data-full");
        lightboxImg.alt = thumbs[current].getAttribute("data-title") || "";
        lightbox.classList.add("is-open");
        document.body.style.overflow = "hidden";
    }

    function close() {
        lightbox.classList.remove("is-open");
        lightboxImg.src = "";
        document.body.style.overflow = "";
    }

    function show(delta) {
        current = (current + delta + thumbs.length) % thumbs.length;
        lightboxImg.src = thumbs[current].getAttribute("data-full");
        lightboxImg.alt = thumbs[current].getAttribute("data-title") || "";
    }

    thumbs.forEach(function (el, i) {
        el.addEventListener("click", function (e) {
            e.preventDefault();
            open(i);
        });
    });

    btnClose.addEventListener("click", close);
    btnPrev.addEventListener("click", function () { show(-1); });
    btnNext.addEventListener("click", function () { show(1); });

    lightbox.addEventListener("click", function (e) {
        if (e.target === lightbox) close();
    });

    document.addEventListener("keydown", function (e) {
        if (!lightbox.classList.contains("is-open")) return;
        if (e.key === "Escape") close();
        if (e.key === "ArrowLeft") show(-1);
        if (e.key === "ArrowRight") show(1);
    });
})();

(function () {
    var mainEl = document.getElementById("videoMain");
    var listEl = document.getElementById("videoList");
    var moreWrap = document.getElementById("videoMoreWrap");
    var showMoreBtn = document.getElementById("videoShowMore");
    var dataEl = document.getElementById("videosData");
    if (!mainEl || !listEl || !moreWrap || !showMoreBtn || !dataEl) return;

    var payload;
    try {
        payload = JSON.parse(dataEl.textContent);
    } catch (e) {
        return;
    }
    var videos = payload && payload.videos;
    if (!videos || !videos.length) return;

    var VISIBLE_LIMIT = 6;
    var byId = {};
    videos.forEach(function (v) { byId[v.id] = v; });

    // Листы из раздела "Материалы", у которых указано видео из этого раздела —
    // под совпадающим видео показываем ссылку на лист ("Лист к этому видео").
    var materialsByVideoId = {};
    var materialsDataEl = document.getElementById("materialsData");
    if (materialsDataEl) {
        try {
            var materialsPayload = JSON.parse(materialsDataEl.textContent);
            (materialsPayload && materialsPayload.materials || []).forEach(function (m) {
                if (m.videoId) materialsByVideoId[m.videoId] = m;
            });
        } catch (e) {
            // материалы необязательны для видео — просто не показываем строку
        }
    }

    var activeId = payload.initialMainId && byId[payload.initialMainId] ? payload.initialMainId : videos[0].id;
    var expanded = false;

    function escapeHtml(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    function thumbMarkup(v, sizeClass) {
        if (v.thumbOk) {
            return '<img src="' + escapeHtml(v.thumb) + '" alt="" loading="lazy" class="' + sizeClass + '">';
        }
        return '<div class="' + sizeClass + ' video-thumb-placeholder"><span>' + escapeHtml(v.title) + "</span></div>";
    }

    function renderMain(autoplay) {
        var v = byId[activeId];
        if (!v) return;
        var cardClass = "video-main-card" + (v.isShorts ? " is-shorts" : "");
        var html;

        if (autoplay) {
            var src = "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(v.id) +
                "?autoplay=1&rel=0&playsinline=1";
            html = '<div class="' + cardClass + '">' +
                '<iframe src="' + src + '" title="' + escapeHtml(v.title) + '" ' +
                'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" ' +
                'referrerpolicy="strict-origin-when-cross-origin" allowfullscreen loading="lazy"></iframe></div>';
        } else {
            html = '<div class="' + cardClass + '">' +
                thumbMarkup(v, "video-main-thumb") +
                '<button type="button" class="video-play-btn" aria-label="Смотреть: ' + escapeHtml(v.title) + '" data-play>' +
                '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M8 5v14l11-7z" fill="#fff"/></svg>' +
                "</button></div>";
        }

        html += '<p class="video-main-title">' + escapeHtml(v.title) + "</p>";
        if (v.note) html += '<p class="video-main-note">' + escapeHtml(v.note) + "</p>";

        var linkedMaterial = materialsByVideoId[v.id];
        if (linkedMaterial) {
            html += '<p class="video-main-link"><a href="#' + escapeHtml(linkedMaterial.id) + '">' +
                "Лист к этому видео: «" + escapeHtml(linkedMaterial.title) + "» →</a></p>";
        }

        mainEl.innerHTML = html;
    }

    function renderList() {
        var rest = videos
            .filter(function (v) { return v.id !== activeId; })
            .sort(function (a, b) { return a.order - b.order; });

        if (!rest.length) {
            moreWrap.hidden = true;
            return;
        }
        moreWrap.hidden = false;

        var hasMore = rest.length > VISIBLE_LIMIT;
        var visible = expanded ? rest : rest.slice(0, VISIBLE_LIMIT);

        listEl.innerHTML = visible.map(function (v) {
            var wrapClass = "video-thumb-wrap" + (v.isShorts ? " is-shorts" : "");
            var shortsTag = v.isShorts ? '<span class="video-list-shorts-tag">Shorts</span>' : "";
            return '<button type="button" class="video-list-item" data-select="' + escapeHtml(v.id) + '">' +
                '<span class="' + wrapClass + '">' + thumbMarkup(v, "video-thumb") + "</span>" +
                '<span class="video-list-text"><span class="video-list-title">' + escapeHtml(v.title) + "</span>" + shortsTag + "</span>" +
                "</button>";
        }).join("");

        showMoreBtn.hidden = !hasMore || expanded;
    }

    function selectVideo(id) {
        if (!byId[id] || id === activeId) return;
        activeId = id;
        renderMain(true);
        renderList();
        mainEl.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    mainEl.addEventListener("click", function (e) {
        if (e.target.closest("[data-play]")) renderMain(true);
    });

    listEl.addEventListener("click", function (e) {
        var btn = e.target.closest(".video-list-item");
        if (btn) selectVideo(btn.getAttribute("data-select"));
    });

    showMoreBtn.addEventListener("click", function () {
        expanded = true;
        renderList();
    });

    renderMain(false);
    renderList();
})();

(function () {
    // Одна настройка, чтобы включить/выключить фильтры по меткам целиком.
    var FILTERS_ENABLED = true;

    var list = document.getElementById("materialsList");
    var dataEl = document.getElementById("materialsData");
    if (!list || !dataEl) return;

    var payload;
    try {
        payload = JSON.parse(dataEl.textContent);
    } catch (e) {
        payload = null;
    }
    var items = (payload && payload.materials) || [];
    var labelsOrder = (payload && payload.labelsOrder) || [];

    var cards = {};
    items.forEach(function (m) {
        var el = document.getElementById(m.id);
        if (el) cards[m.id] = { el: el, labels: m.labels || [] };
    });

    function escapeHtml(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    function reduceMotion() {
        return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    }

    function pluralListov(n) {
        var mod10 = n % 10, mod100 = n % 100;
        if (mod10 === 1 && mod100 !== 11) return "лист";
        if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return "листа";
        return "листов";
    }

    // ---- Фильтры по меткам ----
    var filtersWrap = document.getElementById("materialsFilters");
    var buttonsRow = document.getElementById("materialsFilterButtons");
    var statusEl = document.getElementById("materialsFilterStatus");
    var activeFilter = null; // null = «Все»

    function applyFilter(value) {
        activeFilter = value || null;

        if (buttonsRow) {
            Array.prototype.forEach.call(buttonsRow.querySelectorAll(".materials-filter-btn"), function (btn) {
                var isActive = (btn.getAttribute("data-filter") || null) === activeFilter;
                btn.classList.toggle("is-active", isActive);
                btn.setAttribute("aria-pressed", isActive ? "true" : "false");
            });
        }

        var visibleCount = 0;
        Object.keys(cards).forEach(function (id) {
            var card = cards[id];
            var visible = !activeFilter || card.labels.indexOf(activeFilter) !== -1;
            card.el.classList.toggle("material-card--hidden", !visible);
            if (visible) visibleCount++;
        });

        if (statusEl) {
            statusEl.textContent = activeFilter
                ? "Показано " + visibleCount + " " + pluralListov(visibleCount)
                : "Показаны все листы";
        }
    }

    function buildFilters() {
        if (!FILTERS_ENABLED || !filtersWrap || !buttonsRow) return;

        var counts = {};
        Object.keys(cards).forEach(function (id) {
            cards[id].labels.forEach(function (l) {
                counts[l] = (counts[l] || 0) + 1;
            });
        });

        var shown = labelsOrder.concat(["С видео"]).filter(function (l) {
            return (counts[l] || 0) >= 2;
        });
        if (!shown.length) return;

        var html = '<button type="button" class="materials-filter-btn is-active" data-filter="" aria-pressed="true">Все</button>';
        shown.forEach(function (l) {
            html += '<button type="button" class="materials-filter-btn" data-filter="' + escapeHtml(l) +
                '" aria-pressed="false">' + escapeHtml(l) + "</button>";
        });
        buttonsRow.innerHTML = html;

        buttonsRow.addEventListener("click", function (e) {
            var btn = e.target.closest(".materials-filter-btn");
            if (!btn) return;
            var value = btn.getAttribute("data-filter") || null;
            applyFilter(activeFilter === value && value ? null : value);
        });

        filtersWrap.hidden = false;
    }

    buildFilters();

    // ---- Переход по якорю карточки (#list-...) ----
    var HIGHLIGHT_MS = 2500;
    var highlightTimer = null;

    function goToCard(id) {
        var card = cards[id];
        if (!card) {
            // Отдельной страницы материалов пока нет (все карточки — на главной),
            // поэтому сейчас это никогда не срабатывает. Правило готово на будущее.
            window.location.replace("/materials/#" + id);
            return;
        }

        if (activeFilter && card.labels.indexOf(activeFilter) === -1) {
            applyFilter(null);
        }

        card.el.scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" });

        if (highlightTimer) clearTimeout(highlightTimer);
        card.el.classList.add("is-highlighted");
        highlightTimer = setTimeout(function () {
            card.el.classList.remove("is-highlighted");
            highlightTimer = null;
        }, HIGHLIGHT_MS);
    }

    document.addEventListener("click", function (e) {
        var a = e.target.closest('a[href^="#list-"]');
        if (!a) return;
        var id = a.getAttribute("href").slice(1);
        e.preventDefault();
        if (window.history && history.pushState) history.pushState(null, "", "#" + id);
        goToCard(id);
    });

    if (location.hash.indexOf("#list-") === 0) {
        var initialId = location.hash.slice(1);
        if (cards[initialId]) {
            window.requestAnimationFrame(function () { goToCard(initialId); });
        } else {
            window.location.replace("/materials/" + location.hash);
        }
    }
})();
