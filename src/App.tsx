/**
 * Copyright 2025 Beijing Volcano Engine Technology Co., Ltd. All Rights Reserved.
 * SPDX-license-identifier: BSD-3-Clause
 */

import { BrowserRouter, Routes, Route } from 'react-router-dom';
import EcommerceCSPage from './pages/EcommerceCS';
import '@arco-design/web-react/dist/css/arco.css';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<EcommerceCSPage />} />
        <Route path="/*" element={<EcommerceCSPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
