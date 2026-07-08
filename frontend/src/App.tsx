import { config } from "./config";
import "./App.css";

function App() {
  return (
    <main className="app-shell">
      <section className="app-status" data-api-base-url={config.apiBaseUrl}>
        <h1>Altur</h1>
        <p>Frontend scaffold is ready.</p>
      </section>
    </main>
  );
}

export default App;
