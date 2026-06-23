/* AssetForge — атмосфера «кузницы»: искры, scroll-reveal, лёгкий tilt плиты.
   CSS-first; уважает prefers-reduced-motion. Грузится на всех страницах сайта. */
(function () {
  "use strict";
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- scroll-reveal ---- */
  var els = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && els.length) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { threshold: 0.14, rootMargin: "0px 0px -8% 0px" });
    els.forEach(function (el) { io.observe(el); });
  } else {
    els.forEach(function (el) { el.classList.add("in"); });
  }

  /* ---- ember sparks ---- */
  var cv = document.getElementById("sparks");
  if (cv && !reduce) {
    var ctx = cv.getContext("2d");
    var W, H, parts = [];
    function resize() { W = cv.width = innerWidth; H = cv.height = innerHeight; }
    resize(); addEventListener("resize", resize);
    function spawn() {
      return {
        x: Math.random() * W, y: H + Math.random() * 40,
        r: Math.random() * 1.8 + 0.6,
        vy: -(Math.random() * 0.9 + 0.35), vx: (Math.random() - 0.5) * 0.5,
        life: 0, max: Math.random() * 260 + 160,
        hue: 18 + Math.random() * 24, flick: Math.random() * Math.PI * 2
      };
    }
    var COUNT = innerWidth < 600 ? 32 : 72;
    for (var i = 0; i < COUNT; i++) { var p = spawn(); p.y = Math.random() * H; p.life = Math.random() * p.max; parts.push(p); }
    function tick() {
      ctx.clearRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";
      for (var k = 0; k < parts.length; k++) {
        var q = parts[k];
        q.life++; q.x += q.vx; q.y += q.vy; q.vx += (Math.random() - 0.5) * 0.04; q.flick += 0.2;
        if (q.life > q.max || q.y < -10) { Object.assign(q, spawn()); }
        var t = q.life / q.max;
        var a = (Math.sin(q.flick) * 0.25 + 0.6) * (1 - t) * 0.85;
        var r = q.r * (1 + Math.sin(q.flick) * 0.15);
        var g = ctx.createRadialGradient(q.x, q.y, 0, q.x, q.y, r * 6);
        g.addColorStop(0, "hsla(" + (q.hue + 22) + ",100%,80%," + a + ")");
        g.addColorStop(0.4, "hsla(" + q.hue + ",100%,55%," + (a * 0.6) + ")");
        g.addColorStop(1, "hsla(" + q.hue + ",100%,45%,0)");
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(q.x, q.y, r * 6, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalCompositeOperation = "source-over";
      requestAnimationFrame(tick);
    }
    tick();
  }

  /* ---- forge plate parallax tilt (если есть на странице) ---- */
  var plate = document.querySelector(".plate");
  var host = document.querySelector(".hero .container");
  if (plate && host && !reduce) {
    host.addEventListener("mousemove", function (e) {
      var r = host.getBoundingClientRect();
      var rx = ((e.clientY - r.top) / r.height - 0.5) * -5;
      var ry = ((e.clientX - r.left) / r.width - 0.5) * 6;
      plate.style.transform = "perspective(900px) rotateX(" + rx + "deg) rotateY(" + ry + "deg)";
    });
    host.addEventListener("mouseleave", function () { plate.style.transform = ""; });
  }

  /* ---- live chip flicker in hero plate ---- */
  if (!reduce) {
    var chips = [].slice.call(document.querySelectorAll(".plate .chip"));
    if (chips.length) setInterval(function () {
      chips.forEach(function (c) { if (Math.random() < 0.18) c.classList.toggle("on"); });
    }, 1100);
  }
  /* ---- mobile nav toggle ---- */
  var burger = document.querySelector(".burger");
  var links = document.querySelector(".nav .links");
  if (burger && links) {
    burger.addEventListener("click", function () {
      var open = links.classList.toggle("open");
      burger.setAttribute("aria-expanded", open ? "true" : "false");
    });
    links.addEventListener("click", function (e) {
      if (e.target.tagName === "A") { links.classList.remove("open"); burger.setAttribute("aria-expanded", "false"); }
    });
  }
})();
