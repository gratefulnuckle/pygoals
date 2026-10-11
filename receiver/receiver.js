/* pygoals Cast receiver (CAF v3). No build step.
 *
 * Senders LOAD (or QUEUE_LOAD) goal videos. media.customData.pygoals carries
 * the card: {title, player, number, position, team, teamName, primary,
 * secondary, text, accent, headshot, logo, cardSeconds, lowerSeconds}. The
 * card appears the instant a load is requested (it covers buffering), stays for
 * cardSeconds of playback, then collapses to a lower third. Queue transitions
 * show the next item's card the same way. When nothing is playing for a few
 * seconds the idle screen comes back.
 */
(function () {
  'use strict';

  var DEFAULT_CARD_SECONDS = 3;
  var DEFAULT_LOWER_SECONDS = 8;
  var IDLE_DELAY_MS = 2500; // don't flash idle between back-to-back goals

  var context = cast.framework.CastReceiverContext.getInstance();
  var playerManager = context.getPlayerManager();
  var events = cast.framework.events.EventType;
  var body = document.body;

  var shownKey = null;
  var shownData = null;
  var phase = 'idle';
  var playStartedAt = null;
  var timers = {};

  function $(id) { return document.getElementById(id); }
  function num(v, d) { var n = parseFloat(v); return isFinite(n) && n >= 0 ? n : d; }
  function clearTimer(name) { if (timers[name]) { clearTimeout(timers[name]); timers[name] = null; } }
  function later(name, ms, fn) { clearTimer(name); timers[name] = setTimeout(function () { timers[name] = null; fn(); }, ms); }

  function setPhase(next) {
    phase = next;
    body.classList.remove('idle', 'card', 'lower', 'video');
    body.classList.add(next);
  }

  function mediaKey(media) {
    if (!media) { return null; }
    return media.contentId || media.contentUrl || media.entity || null;
  }

  function cardData(media) {
    if (!media) { return null; }
    var cd = media.customData || {};
    var p = cd.pygoals || null;
    var md = media.metadata || {};
    if (!p && !md.title) { return null; }
    p = p || {};
    return {
      title: p.title || md.title || '',
      player: p.player || md.subtitle || '',
      number: p.number || '',
      position: p.position || '',
      team: p.team || '',
      teamName: p.teamName || p.team || '',
      primary: p.primary || '#1f2a44',
      secondary: p.secondary || '#0b0e14',
      text: p.text || '#ffffff',
      accent: p.accent || p.secondary || '#4f8cff',
      headshot: p.headshot || (md.images && md.images[0] && md.images[0].url) || '',
      logo: p.logo || '',
      cardSeconds: num(p.cardSeconds, DEFAULT_CARD_SECONDS),
      lowerSeconds: num(p.lowerSeconds, DEFAULT_LOWER_SECONDS)
    };
  }

  function setImg(id, url) {
    var img = $(id);
    if (url) { img.src = url; img.style.visibility = 'visible'; }
    else { img.removeAttribute('src'); img.style.visibility = 'hidden'; }
  }

  function fill(d) {
    var root = document.documentElement.style;
    root.setProperty('--team', d.primary);
    root.setProperty('--team2', d.secondary);
    root.setProperty('--team-text', d.text);
    root.setProperty('--team-accent', d.accent);
    setImg('card-headshot', d.headshot);
    setImg('card-logo', d.logo);
    setImg('lower-logo', d.logo);
    $('card-team').textContent = (d.teamName || '').toUpperCase();
    $('card-player').textContent = d.player || d.title;
    var meta = [];
    if (d.number) { meta.push('#' + d.number); }
    if (d.position) { meta.push(d.position); }
    if (d.team) { meta.push(d.team); }
    $('card-meta').textContent = meta.join('  \u00b7  ');
    $('card-title').textContent = d.player ? d.title : '';
    $('lower-player').textContent = d.player || d.title;
    $('lower-title').textContent = d.player ? d.title : '';
  }

  /** Show the full card for this media (idempotent per media). */
  function showCard(media) {
    var key = mediaKey(media);
    if (!key || key === shownKey) { return; }
    clearTimer('idle');
    clearTimer('collapse');
    clearTimer('lowerOut');
    shownKey = key;
    shownData = cardData(media);
    playStartedAt = null;
    if (!shownData) { setPhase('video'); return; }
    fill(shownData);
    body.classList.add('buffering');
    setPhase('card');
  }

  function onPlaying() {
    clearTimer('idle');
    body.classList.remove('buffering');
    var media = playerManager.getMediaInformation();
    if (mediaKey(media) !== shownKey) { showCard(media); }
    if (playStartedAt !== null || !shownData) {
      if (phase === 'idle') { setPhase('video'); }
      return;
    }
    playStartedAt = Date.now();
    var d = shownData;
    var bar = $('card-progress-bar');
    bar.style.transition = 'none';
    bar.style.width = '0';
    void bar.offsetWidth; // restart the transition
    bar.style.transition = 'width ' + d.cardSeconds + 's linear';
    bar.style.width = '100%';
    later('collapse', d.cardSeconds * 1000, function () {
      if (d.lowerSeconds > 0) {
        setPhase('lower');
        later('lowerOut', d.lowerSeconds * 1000, function () { setPhase('video'); });
      } else {
        setPhase('video');
      }
    });
  }

  function maybeIdle() {
    later('idle', IDLE_DELAY_MS, function () {
      var state = playerManager.getPlayerState();
      if (state === cast.framework.messages.PlayerState.IDLE || !playerManager.getMediaInformation()) {
        shownKey = null;
        shownData = null;
        setPhase('idle');
      }
    });
  }

  // The card appears as soon as the sender asks for a goal: no gap, no backdrop.
  playerManager.setMessageInterceptor(cast.framework.messages.MessageType.LOAD, function (request) {
    if (request && request.media) { showCard(request.media); }
    return request;
  });
  playerManager.setMessageInterceptor(cast.framework.messages.MessageType.QUEUE_LOAD, function (request) {
    var items = request && request.items;
    var start = (request && request.startIndex) || 0;
    if (items && items[start] && items[start].media) { showCard(items[start].media); }
    return request;
  });

  // Queue transitions (next item starts loading) and loads that bypassed the interceptor.
  playerManager.addEventListener(events.PLAYER_LOAD_COMPLETE, function () {
    showCard(playerManager.getMediaInformation());
  });
  if (events.PLAYER_LOADING) {
    playerManager.addEventListener(events.PLAYER_LOADING, function (e) {
      if (e && e.media) { showCard(e.media); }
    });
  }
  playerManager.addEventListener(events.PLAYING, onPlaying);
  playerManager.addEventListener(events.BUFFERING, function (e) {
    if (e && e.isBuffering) { body.classList.add('buffering'); } else { body.classList.remove('buffering'); }
  });
  playerManager.addEventListener(events.MEDIA_FINISHED, maybeIdle);
  playerManager.addEventListener(events.ERROR, maybeIdle);
  playerManager.addEventListener(events.ABORT, maybeIdle);
  playerManager.addEventListener(events.MEDIA_STATUS, function (e) {
    var status = e && e.mediaStatus;
    if (status && status.playerState === 'IDLE') { maybeIdle(); }
  });

  function tick() {
    var now = new Date();
    $('idle-clock').textContent = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }
  tick();
  setInterval(tick, 10000);

  var options = new cast.framework.CastReceiverOptions();
  options.disableIdleTimeout = true; // keep the idle screen up between goals
  options.maxInactivity = 3600;
  context.start(options);
})();
