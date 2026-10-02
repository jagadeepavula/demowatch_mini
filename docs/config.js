const h = location.hostname;
window.API_URL = (h === "localhost" || h === "127.0.0.1") ? ""
			   : (h === "" ? "http://localhost:8080" : "https://demowatch-mini-704694697824.us-central1.run.app");
