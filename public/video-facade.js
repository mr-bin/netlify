/* Превью видео на тематических страницах, подборках и в статьях к видео
   (макрос video_facade в partials/icons.html): до клика страница не
   обращается к YouTube, по клику на месте превью появляется плеер
   youtube-nocookie и сразу начинает воспроизведение — как на главной. */
(function () {
    document.addEventListener("click", function (e) {
        var btn = e.target.closest(".video-facade [data-play]");
        if (!btn) return;
        e.preventDefault();
        var box = btn.closest(".video-facade");
        var iframe = document.createElement("iframe");
        iframe.src = "https://www.youtube-nocookie.com/embed/" +
            encodeURIComponent(box.getAttribute("data-video-id")) + "?autoplay=1&rel=0&playsinline=1";
        iframe.title = box.getAttribute("data-video-title") || "";
        iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
        iframe.referrerPolicy = "strict-origin-when-cross-origin";
        iframe.allowFullscreen = true;
        box.parentNode.replaceChild(iframe, box);
        iframe.focus();
    });
})();
