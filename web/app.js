/* ══════════════════════════════════════════════════════════════
   MakineRAG — arayüz mantığı. Dış bağımlılık yok.
   ══════════════════════════════════════════════════════════════ */
"use strict";

const $  = (s, k = document) => k.querySelector(s);
const $$ = (s, k = document) => [...k.querySelectorAll(s)];

const D = {
  makine: null,
  tur: null,
  sekme: "sohbet",
  gecmis: [],          // [{role, content}] — sunucuya gönderilen kısa hafıza
  akisDurdur: null,    // AbortController
  belge: { ofset: 0, limit: 60, sirala: "dosya_adi", yon: "asc", q: "", toplam: 0 },
  raporSecili: null,
  isSayaci: null,
};

/* ── API ─────────────────────────────────────────────────── */
async function api(yol, secenek) {
  const y = await fetch("/api" + yol, secenek);
  if (!y.ok) {
    let m = y.status + " " + y.statusText;
    try { m = (await y.json()).detail || m; } catch (_) {}
    throw new Error(m);
  }
  return y.json();
}

const sayiBicim = (n) =>
  (n === null || n === undefined) ? "—" : Number(n).toLocaleString("tr-TR");

function bildir(mesaj, tur = "") {
  const el = document.createElement("div");
  el.className = "bildirim " + tur;
  el.textContent = mesaj;
  $("#bildirim-alani").append(el);
  setTimeout(() => {
    el.style.transition = "opacity .3s, transform .3s";
    el.style.opacity = "0";
    el.style.transform = "translateY(8px)";
    setTimeout(() => el.remove(), 320);
  }, 4200);
}

/* ── Metin güvenliği + markdown ──────────────────────────── */
const kacir = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

function satirIci(s, atif) {
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  s = s.replace(/(^|[\s(])_([^_\n]+)_/g, "$1<em>$2</em>");
  if (atif) s = s.replace(/\[(\d{1,2})\]/g, '<span class="atif" data-no="$1">$1</span>');
  return s;
}

/** Küçük ama tam markdown çevirici: başlık, liste, tablo, kod, çizgi. */
function md(ham, secenek = {}) {
  const atif = secenek.atif !== false;
  const satirlar = kacir(ham).split("\n");
  const cikti = [];
  let liste = null, kodda = false, kod = [];

  const listeKapat = () => { if (liste) { cikti.push("</" + liste + ">"); liste = null; } };

  for (let i = 0; i < satirlar.length; i++) {
    const s = satirlar[i];

    if (/^\s*```/.test(s)) {
      if (kodda) { cikti.push("<pre><code>" + kod.join("\n") + "</code></pre>"); kod = []; }
      kodda = !kodda;
      continue;
    }
    if (kodda) { kod.push(s); continue; }

    if (!s.trim()) { listeKapat(); continue; }

    // tablo: | a | b |  +  ayırıcı satırı
    if (/^\s*\|/.test(s) && i + 1 < satirlar.length && /^\s*\|[\s:|-]+\|\s*$/.test(satirlar[i + 1])) {
      listeKapat();
      const hucre = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const bas = hucre(s);
      let j = i + 2;
      const govde = [];
      while (j < satirlar.length && /^\s*\|/.test(satirlar[j])) { govde.push(hucre(satirlar[j])); j++; }
      cikti.push(
        "<table><thead><tr>" + bas.map((c) => "<th>" + satirIci(c, atif) + "</th>").join("") +
        "</tr></thead><tbody>" +
        govde.map((r) => "<tr>" + r.map((c) => "<td>" + satirIci(c, atif) + "</td>").join("") + "</tr>").join("") +
        "</tbody></table>"
      );
      i = j - 1;
      continue;
    }

    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(s)) { listeKapat(); cikti.push("<hr>"); continue; }

    const b = s.match(/^(#{1,4})\s+(.*)$/);
    if (b) {
      listeKapat();
      const d = b[1].length;
      cikti.push("<h" + d + ">" + satirIci(b[2], atif) + "</h" + d + ">");
      continue;
    }

    const ml = s.match(/^\s*[-*•]\s+(.*)$/);
    if (ml) {
      if (liste !== "ul") { listeKapat(); cikti.push("<ul>"); liste = "ul"; }
      cikti.push("<li>" + satirIci(ml[1], atif) + "</li>");
      continue;
    }

    const nl = s.match(/^\s*\d+[.)]\s+(.*)$/);
    if (nl) {
      if (liste !== "ol") { listeKapat(); cikti.push("<ol>"); liste = "ol"; }
      cikti.push("<li>" + satirIci(nl[1], atif) + "</li>");
      continue;
    }

    listeKapat();
    cikti.push("<p>" + satirIci(s, atif) + "</p>");
  }
  listeKapat();
  if (kodda && kod.length) cikti.push("<pre><code>" + kod.join("\n") + "</code></pre>");
  return cikti.join("");
}

/* ── Tema ────────────────────────────────────────────────── */
function temaKur() {
  const kayit = localStorage.getItem("makinerag-tema");
  if (kayit) document.documentElement.dataset.tema = kayit;
  $("#tema-dugme").onclick = () => {
    const yeni = document.documentElement.dataset.tema === "acik" ? "koyu" : "acik";
    document.documentElement.dataset.tema = yeni;
    localStorage.setItem("makinerag-tema", yeni);
  };
}

/* ── Sekmeler ────────────────────────────────────────────── */
function sekmeKur() {
  $$(".sekme").forEach((d) => {
    d.onclick = () => {
      D.sekme = d.dataset.sekme;
      $$(".sekme").forEach((x) => x.classList.toggle("aktif", x === d));
      $$(".sekme-icerik").forEach((x) =>
        x.classList.toggle("aktif", x.id === "sekme-" + D.sekme));
      if (D.sekme === "belgeler") belgeleriYukle(true);
      if (D.sekme === "rapor") { raporlariYukle(); uretDugmeleriKur(); }
    };
  });
}

/* ── Durum + filtreler ───────────────────────────────────── */
async function durumYukle() {
  try {
    const d = await api("/durum");
    $("#ist-belge").textContent = sayiBicim(d.belge_sayisi);
    $("#ist-sayfa").textContent = sayiBicim(d.sayfa_sayisi);
    $("#ist-ocr").textContent   = sayiBicim(d.ocr_sayfa_sayisi);
    $("#ist-parca").textContent = sayiBicim(d.parca_sayisi);
    $("#motor-llm").textContent = d.llm_model;
    $("#motor-gomme").textContent = d.gomme_model;
    $("#sekme-belge-sayi").textContent = sayiBicim(d.belge_sayisi);

    const nokta = $("#rozet-durum .nokta");
    const metin = $("#rozet-metin");
    if (!d.ollama) {
      nokta.className = "nokta hata"; metin.textContent = "Ollama kapalı";
    } else if (d.motor === "yukleniyor") {
      nokta.className = "nokta bekle"; metin.textContent = "model yükleniyor";
    } else if (d.motor === "hata") {
      nokta.className = "nokta hata"; metin.textContent = "motor hatası";
    } else if (!d.parca_sayisi) {
      nokta.className = "nokta bekle"; metin.textContent = "indeks boş";
    } else {
      nokta.className = "nokta iyi";
      metin.textContent = sayiBicim(d.belge_sayisi) + " belge hazır";
    }
  } catch (e) {
    $("#rozet-durum .nokta").className = "nokta hata";
    $("#rozet-metin").textContent = "sunucuya bağlanılamadı";
  }
}

async function filtreYukle() {
  const makineler = await api("/makineler");
  const kap = $("#makine-liste");
  kap.innerHTML = "";

  const toplam = makineler.reduce((t, m) => t + m.belge_sayisi, 0);
  const hepsi = { kod: null, ad: "Tüm belgeler", belge_sayisi: toplam, sayfa_sayisi: 0 };

  [hepsi, ...makineler].forEach((m) => {
    const d = document.createElement("button");
    d.className = "makine-ogesi" + (D.makine === m.kod ? " aktif" : "");
    d.innerHTML =
      '<span class="makine-kod">' + kacir(m.kod ? String(m.kod).slice(0, 3) : "∗") + "</span>" +
      '<span class="makine-bilgi">' +
        '<span class="makine-ad">' + kacir(m.ad) + "</span>" +
        '<span class="makine-alt">' + sayiBicim(m.belge_sayisi) + " belge" +
          (m.sayfa_sayisi ? " · " + sayiBicim(m.sayfa_sayisi) + " sayfa" : "") +
        "</span>" +
      "</span>";
    d.onclick = () => {
      D.makine = m.kod;
      $$(".makine-ogesi").forEach((x) => x.classList.toggle("aktif", x === d));
      filtreCipGuncelle();
      if (D.sekme === "belgeler") belgeleriYukle(true);
    };
    kap.append(d);
  });

  const turler = await api("/turler");
  const sec = $("#tur-secim");
  sec.innerHTML = '<option value="">Tüm türler</option>';
  turler.forEach((t) => {
    const o = document.createElement("option");
    o.value = t.tur;
    o.textContent = t.tur + " (" + t.sayi + ")";
    sec.append(o);
  });
  sec.onchange = () => {
    D.tur = sec.value || null;
    filtreCipGuncelle();
    if (D.sekme === "belgeler") belgeleriYukle(true);
  };
}

function filtreCipGuncelle() {
  const parca = [];
  if (D.makine) {
    const ad = $$(".makine-ogesi.aktif .makine-ad")[0];
    parca.push(ad ? ad.textContent : D.makine);
  }
  if (D.tur) parca.push(D.tur);
  const ust = $("#besteci-ust");
  if (!parca.length) { ust.hidden = true; return; }
  ust.hidden = false;
  $("#filtre-cip").textContent = "Arama kapsamı: " + parca.join(" · ");
}

/* ── Sohbet ──────────────────────────────────────────────── */
function mesajEkle(rol) {
  $("#bos-durum")?.remove();
  const el = document.createElement("div");
  el.className = "mesaj " + rol;
  $("#mesajlar").append(el);
  return el;
}

function asagiKaydir() {
  const m = $("#mesajlar");
  m.scrollTop = m.scrollHeight;
}

function kaynakKartlari(kaynaklar) {
  return (
    '<div class="kaynaklar">' +
      '<div class="kaynaklar-baslik">Kaynaklar · ' + kaynaklar.length + " belge parçası</div>" +
      '<div class="kaynak-izgara">' +
      kaynaklar.map((k) =>
        '<div class="kaynak-kart" data-no="' + k.no + '" data-doc="' + kacir(k.doc_id) +
             '" data-sayfa="' + k.sayfa_no + '">' +
          '<div class="kaynak-ust">' +
            '<span class="kaynak-no">' + k.no + "</span>" +
            '<span class="kaynak-baslik" title="' + kacir(k.baslik) + '">' + kacir(k.baslik) + "</span>" +
            (k.makine && k.makine !== "bilinmiyor"
              ? '<span class="etiket makine">' + kacir(k.makine) + "</span>" : "") +
          "</div>" +
          '<div class="kaynak-orta">' + kacir(k.dosya) + " · s." + kacir(k.sayfa) + "</div>" +
          '<div class="kaynak-alinti">' + kacir(k.alinti) + "</div>" +
        "</div>").join("") +
      "</div></div>"
  );
}

function kaynakBagla(kok) {
  $$(".kaynak-kart", kok).forEach((kart) => {
    kart.onclick = () => belgeAc(kart.dataset.doc, Number(kart.dataset.sayfa));
  });
  $$(".atif", kok).forEach((a) => {
    a.onclick = () => {
      const hedef = $('.kaynak-kart[data-no="' + a.dataset.no + '"]', kok);
      if (!hedef) return;
      hedef.scrollIntoView({ behavior: "smooth", block: "center" });
      hedef.classList.add("parla");
      setTimeout(() => hedef.classList.remove("parla"), 1400);
    };
  });
}

async function sor(soru) {
  if (!soru.trim() || D.akisDurdur) return;

  const kul = mesajEkle("kullanici");
  kul.innerHTML = '<div class="balon"></div>';
  $(".balon", kul).textContent = soru;

  const asis = mesajEkle("asistan");
  asis.innerHTML =
    '<div class="avatar"><svg viewBox="0 0 24 24">' +
      '<path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z"/>' +
      '<path d="M19.4 13a7.6 7.6 0 0 0 0-2l2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-1.7-1l-.4-2.6h-3.9l-.4 2.6a7.6 7.6 0 0 0-1.7 1l-2.4-1-2 3.4L6.6 11a7.6 7.6 0 0 0 0 2l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 0 0 1.7 1l.4 2.6h3.9l.4-2.6a7.6 7.6 0 0 0 1.7-1l2.4 1 2-3.4-2-1.6z"/>' +
    "</svg></div>" +
    '<div class="asistan-govde">' +
      '<div class="dusunuyor"><i></i><i></i><i></i><span>belgeler taranıyor…</span></div>' +
    "</div>";
  const govde = $(".asistan-govde", asis);
  asagiKaydir();

  const dugme = $("#gonder");
  dugme.classList.add("calisiyor");
  dugme.title = "Durdur";
  D.akisDurdur = new AbortController();

  let cevap = "", kaynaklar = [], bekleyenCizim = false;

  const ciz = (bitti) => {
    govde.innerHTML =
      '<div class="cevap">' + md(cevap) + (bitti ? "" : '<span class="imlec"></span>') + "</div>" +
      (kaynaklar.length ? kaynakKartlari(kaynaklar) : "");
    kaynakBagla(govde);
  };

  try {
    const y = await fetch("/api/sor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: D.akisDurdur.signal,
      body: JSON.stringify({ soru, makine: D.makine, tur: D.tur, gecmis: D.gecmis.slice(-4) }),
    });
    if (!y.ok) throw new Error("Sunucu " + y.status);

    const okuyucu = y.body.getReader();
    const cozucu = new TextDecoder();
    let tampon = "";

    while (true) {
      const { value, done } = await okuyucu.read();
      if (done) break;
      tampon += cozucu.decode(value, { stream: true });

      let sinir;
      while ((sinir = tampon.indexOf("\n\n")) !== -1) {
        const blok = tampon.slice(0, sinir);
        tampon = tampon.slice(sinir + 2);

        const olayEs = blok.match(/^event:\s*(.+)$/m);
        const veriEs = blok.match(/^data:\s*([\s\S]+)$/m);
        if (!olayEs || !veriEs) continue;
        let veri; try { veri = JSON.parse(veriEs[1]); } catch (_) { continue; }

        if (olayEs[1] === "kaynaklar") {
          kaynaklar = veri;
          ciz(false);
        } else if (olayEs[1] === "parca") {
          cevap += veri.t;
          if (!bekleyenCizim) {
            bekleyenCizim = true;
            requestAnimationFrame(() => { bekleyenCizim = false; ciz(false); asagiKaydir(); });
          }
        } else if (olayEs[1] === "bitti") {
          ciz(true);
          govde.insertAdjacentHTML("beforeend",
            '<div class="cevap-alt"><span>' + veri.sure + " sn</span>" +
            '<button class="metin-dugme" data-kopyala>Cevabı kopyala</button></div>');
          $("[data-kopyala]", govde).onclick = () => {
            navigator.clipboard.writeText(cevap).then(() => bildir("Cevap kopyalandı", "iyi"));
          };
        } else if (olayEs[1] === "hata") {
          throw new Error(veri.mesaj);
        }
      }
    }

    if (cevap.trim()) {
      D.gecmis.push({ role: "user", content: soru });
      D.gecmis.push({ role: "assistant", content: cevap });
      D.gecmis = D.gecmis.slice(-6);
    }
  } catch (e) {
    if (e.name === "AbortError") {
      ciz(true);
      govde.insertAdjacentHTML("beforeend",
        '<div class="cevap-alt"><span>durduruldu</span></div>');
    } else {
      govde.innerHTML = '<div class="hata-kutu">Hata: ' + kacir(e.message) + "</div>";
    }
  } finally {
    D.akisDurdur = null;
    dugme.classList.remove("calisiyor");
    dugme.title = "Gönder (Enter)";
    asagiKaydir();
  }
}

function sohbetKur() {
  const alan = $("#soru");
  const dugme = $("#gonder");

  const boyutla = () => {
    alan.style.height = "auto";
    alan.style.height = Math.min(alan.scrollHeight, 190) + "px";
  };
  alan.addEventListener("input", boyutla);

  alan.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const s = alan.value;
      alan.value = ""; boyutla();
      sor(s);
    }
  });

  dugme.onclick = () => {
    if (D.akisDurdur) { D.akisDurdur.abort(); return; }
    const s = alan.value;
    alan.value = ""; $("#soru").style.height = "auto";
    sor(s);
  };

  $$(".ornek").forEach((o) => { o.onclick = () => sor(o.textContent); });

  $("#temizle-sohbet").onclick = () => {
    D.gecmis = [];
    $("#mesajlar").innerHTML =
      '<div class="bos-durum" id="bos-durum"><h2>Sohbet temizlendi</h2>' +
      "<p>Yeni bir soru sorabilirsiniz. Önceki konuşma hafızası sıfırlandı.</p></div>";
  };
}

/* ── Belgeler ────────────────────────────────────────────── */
async function belgeleriYukle(sifirla) {
  if (sifirla) { D.belge.ofset = 0; $("#belge-govde").innerHTML = ""; }
  const p = new URLSearchParams({
    sirala: D.belge.sirala, yon: D.belge.yon,
    limit: D.belge.limit, ofset: D.belge.ofset,
  });
  if (D.makine) p.set("makine", D.makine);
  if (D.tur) p.set("tur", D.tur);
  if (D.belge.q) p.set("q", D.belge.q);

  let veri;
  try { veri = await api("/belgeler?" + p); }
  catch (e) { bildir("Belgeler yüklenemedi: " + e.message, "hata"); return; }

  D.belge.toplam = veri.toplam;
  $("#belge-sayi").textContent = sayiBicim(veri.toplam) + " belge";

  const govde = $("#belge-govde");
  if (!veri.kayitlar.length && !D.belge.ofset) {
    govde.innerHTML =
      '<tr><td colspan="6" class="bos-satir">Bu filtreye uyan belge yok. ' +
      "Filtreleri gevşetin ya da <code>python src/cli.py meta</code> adımını çalıştırın.</td></tr>";
    $("#daha-fazla").hidden = true;
    return;
  }

  veri.kayitlar.forEach((k) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      '<td class="hucre-baslik">' + kacir(k.baslik_tr || "—") + "</td>" +
      '<td class="hucre-dosya" title="' + kacir(k.dosya_adi) + '">' + kacir(k.dosya_adi) + "</td>" +
      "<td>" + (k.makine && k.makine !== "bilinmiyor"
        ? '<span class="etiket makine">' + kacir(k.makine) + "</span>"
        : '<span class="etiket">—</span>') + "</td>" +
      '<td><span class="etiket">' + kacir(k.belge_turu || "diğer") + "</span></td>" +
      '<td class="sag hucre-sayi">' + sayiBicim(k.sayfa_sayisi) + "</td>" +
      '<td class="sag"><button class="mini-dugme" data-pdf>PDF</button></td>';
    tr.onclick = () => belgeAc(k.doc_id, 1);
    $("[data-pdf]", tr).onclick = (e) => {
      e.stopPropagation();
      window.open("/api/belge/" + k.doc_id + "/pdf", "_blank");
    };
    govde.append(tr);
  });

  D.belge.ofset += veri.kayitlar.length;
  $("#daha-fazla").hidden = D.belge.ofset >= veri.toplam;
}

function belgelerKur() {
  let zaman;
  $("#belge-ara").addEventListener("input", (e) => {
    clearTimeout(zaman);
    zaman = setTimeout(() => { D.belge.q = e.target.value.trim(); belgeleriYukle(true); }, 260);
  });

  $$("#belge-tablo th.sirali").forEach((th) => {
    th.onclick = () => {
      const alan = th.dataset.alan;
      if (D.belge.sirala === alan) {
        D.belge.yon = D.belge.yon === "asc" ? "desc" : "asc";
      } else {
        D.belge.sirala = alan; D.belge.yon = "asc";
      }
      $$("#belge-tablo th").forEach((x) => x.classList.remove("artan", "azalan"));
      th.classList.add(D.belge.yon === "asc" ? "artan" : "azalan");
      belgeleriYukle(true);
    };
  });

  $("#daha-fazla").onclick = () => belgeleriYukle(false);
}

/* ── Belge çekmecesi ─────────────────────────────────────── */
async function belgeAc(docId, sayfa) {
  const perde = $("#cekmece-perde"), cek = $("#cekmece");
  perde.hidden = false; cek.hidden = false;
  $("#cekmece-govde").innerHTML = '<div class="iskele" style="height:120px"></div>';

  let b;
  try { b = await api("/belge/" + docId); }
  catch (e) { $("#cekmece-govde").innerHTML = '<div class="hata-kutu">' + kacir(e.message) + "</div>"; return; }

  $("#cekmece-baslik").textContent = b.baslik_tr || b.dosya_adi;
  $("#cekmece-dosya").textContent = b.dosya_adi;

  const pdfUrl = "/api/belge/" + docId + "/pdf#page=" + (sayfa || 1);
  const sayfalar = b.sayfalar || [];

  $("#cekmece-govde").innerHTML =
    '<div class="cek-bolum"><a class="birincil-dugme" href="' + pdfUrl + '" target="_blank">' +
      '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>' +
      "PDF&#39;i aç" + (sayfa > 1 ? " (sayfa " + sayfa + ")" : "") + "</a>" +
      (b.pdf_var ? "" : '<p class="cek-metin" style="margin-top:8px;color:var(--hata)">Kaynak PDF diskte bulunamadı.</p>') +
    "</div>" +

    '<div class="cek-bolum"><div class="cek-izgara">' +
      '<div class="cek-kutu"><span>Sayfa</span><b>' + sayiBicim(b.sayfa_sayisi) + "</b></div>" +
      '<div class="cek-kutu"><span>OCR&#39;lı sayfa</span><b>' + sayiBicim(b.ocr_sayfa_sayisi) + "</b></div>" +
      '<div class="cek-kutu"><span>Makine</span><b>' + kacir(b.makine) + "</b></div>" +
      '<div class="cek-kutu"><span>Tür</span><b style="font-size:13px">' + kacir(b.belge_turu) + "</b></div>" +
    "</div></div>" +

    (b.ozet_tr ? '<div class="cek-bolum"><div class="cek-baslik">Özet</div>' +
      '<div class="cek-metin">' + kacir(b.ozet_tr) + "</div></div>" : "") +

    ((b.anahtar_kelimeler_tr || []).length
      ? '<div class="cek-bolum"><div class="cek-baslik">Anahtar kelimeler</div><div class="anahtarlar">' +
        b.anahtar_kelimeler_tr.map((a) => '<span class="etiket">' + kacir(a) + "</span>").join("") +
        "</div></div>" : "") +

    ((b.makine_adaylari || []).length
      ? '<div class="cek-bolum"><div class="cek-baslik">Metinde geçen makine adları</div><div class="anahtarlar">' +
        b.makine_adaylari.map((a) => '<span class="etiket">' + kacir(a) + "</span>").join("") +
        "</div></div>" : "") +

    (sayfalar.length
      ? '<div class="cek-bolum"><div class="cek-baslik">Sayfalar · turuncu = OCR ile okundu</div>' +
        '<div class="sayfa-serit">' +
        sayfalar.map((s) =>
          '<a class="sayfa-kare' + (s.ocr ? " ocr" : "") + (s.uzunluk < 40 ? " bos" : "") +
          '" href="/api/belge/' + docId + "/pdf#page=" + s.sayfa +
          '" target="_blank" title="' + kacir(s.onizleme.slice(0, 120)) + '">' + s.sayfa + "</a>").join("") +
        "</div></div>" : "") +

    '<div class="cek-bolum"><div class="cek-baslik">Disk yolu</div>' +
      '<div class="cek-metin" style="font-family:ui-monospace,Consolas,monospace;font-size:11.5px">' +
      kacir(b.kaynak) + "</div></div>";
}

function cekmeceKur() {
  const kapat = () => { $("#cekmece").hidden = true; $("#cekmece-perde").hidden = true; };
  $("#cekmece-kapat").onclick = kapat;
  $("#cekmece-perde").onclick = kapat;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") kapat(); });
}

/* ── Raporlar ────────────────────────────────────────────── */
async function raporlariYukle() {
  const kap = $("#rapor-liste");
  let liste;
  try { liste = await api("/raporlar"); }
  catch (_) { return; }

  if (!liste.length) {
    kap.innerHTML = '<div style="font-size:12px;color:var(--soluk);padding:4px 2px">Henüz rapor yok.</div>';
    return;
  }
  kap.innerHTML = "";
  liste.forEach((r) => {
    const d = document.createElement("button");
    d.className = "rapor-ogesi" + (D.raporSecili === r.ad ? " aktif" : "");
    d.dataset.ad = r.ad;
    const t = new Date(r.guncelleme * 1000);
    d.innerHTML = kacir(r.ad.replace(/\.md$/, "").replace(/_/g, " ")) +
      "<small>" + t.toLocaleDateString("tr-TR") + " " +
      t.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }) + "</small>";
    d.onclick = () => raporAc(r.ad);
    kap.append(d);
  });
  if (!D.raporSecili && liste.length) raporAc(liste[0].ad);
}

async function raporAc(ad) {
  D.raporSecili = ad;
  $$(".rapor-ogesi").forEach((x) => x.classList.toggle("aktif", x.dataset.ad === ad));
  const govde = $("#rapor-govde");
  govde.innerHTML = '<div class="iskele" style="height:300px"></div>';
  try {
    const r = await api("/raporlar/" + encodeURIComponent(ad));
    govde.innerHTML = '<div class="md">' + md(r.icerik, { atif: false }) + "</div>";
    govde.scrollTop = 0;
  } catch (e) {
    govde.innerHTML = '<div class="hata-kutu">' + kacir(e.message) + "</div>";
  }
}

async function uretDugmeleriKur() {
  const kap = $("#rapor-uret-liste");
  if (kap.dataset.hazir) return;
  kap.dataset.hazir = "1";
  const makineler = await api("/makineler");
  makineler.filter((m) => m.kod !== "bilinmiyor").forEach((m) => {
    const d = document.createElement("button");
    d.className = "uret-dugme";
    d.innerHTML = "<span>+</span><span>" + kacir(m.ad) + " (" + m.belge_sayisi + " belge)</span>";
    d.onclick = async () => {
      d.disabled = true;
      try {
        await api("/raporlar/uret", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ makine: m.kod }),
        });
        bildir(m.ad + " için konu haritası üretimi başladı. Bu işlem uzun sürebilir.", "iyi");
        isleriIzle();
      } catch (e) {
        bildir("Başlatılamadı: " + e.message, "hata");
      } finally {
        d.disabled = false;
      }
    };
    kap.append(d);
  });
  isleriIzle();
}

async function isleriGoster() {
  let liste;
  try { liste = await api("/isler"); } catch (_) { return false; }
  const kap = $("#is-liste");
  kap.innerHTML = liste.map((i) =>
    '<div class="is-ogesi ' + i.durum + '">' +
      kacir(i.baslik) + ' — <span class="is-durum">' + i.durum + "</span>" +
      (i.hata ? '<div style="color:var(--hata);margin-top:4px">' + kacir(i.hata.slice(0, 120)) + "</div>" : "") +
      (i.durum === "calisiyor" ? '<div class="ilerleme"><i></i></div>' : "") +
    "</div>").join("");
  return liste.some((i) => i.durum === "calisiyor" || i.durum === "kuyrukta");
}

function isleriIzle() {
  clearInterval(D.isSayaci);
  const tik = async () => {
    const devam = await isleriGoster();
    if (!devam) { clearInterval(D.isSayaci); raporlariYukle(); }
  };
  tik();
  D.isSayaci = setInterval(tik, 4000);
}

/* ── Başlangıç ───────────────────────────────────────────── */
(async function baslat() {
  temaKur();
  sekmeKur();
  sohbetKur();
  belgelerKur();
  cekmeceKur();
  await durumYukle();
  try { await filtreYukle(); }
  catch (e) { bildir("Filtreler yüklenemedi: " + e.message, "hata"); }
  setInterval(durumYukle, 20000);
  $("#soru").focus();
})();
