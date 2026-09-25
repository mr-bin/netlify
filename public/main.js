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
