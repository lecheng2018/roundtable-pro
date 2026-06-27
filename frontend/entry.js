var QP = window.QwenPaw || window.QP;
if (!QP) {
  console.error("[roundtable-pro] QwenPaw not available");
} else {
  var React = QP.host.React;
  var h = React.createElement;
  var useEffect = React.useEffect;
  var useRef = React.useRef;

  function RoundTableProPage() {
    var containerRef = useRef(null);
    var iframeRef = useRef(null);

    useEffect(function() {
      var iframe = document.createElement("iframe");
      iframe.src = "/api/frontend_plugin/roundtable-pro/files/frontend/index.html?_t=" + Date.now();
      iframe.style.width = "100%";
      iframe.style.height = "100%";
      iframe.style.border = "none";
      iframe.style.background = "#0f172a";
      iframeRef.current = iframe;
      if (containerRef.current) {
        containerRef.current.appendChild(iframe);
      }
      return function() {
        if (iframe.parentNode) iframe.parentNode.removeChild(iframe);
      };
    }, []);

    return h("div", { ref: containerRef, style: { width: "100%", height: "100%" } });
  }

  QP.registerRoutes("roundtable-pro", [
    {
      path: "/plugin/roundtable-pro",
      component: RoundTableProPage,
      label: "圆桌 Pro",
      icon: "🪑",
      priority: 100
    }
  ]);
}