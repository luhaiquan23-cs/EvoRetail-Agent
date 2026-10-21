import { configureStore, createSlice } from '@reduxjs/toolkit';

const appSlice = createSlice({
  name: 'app',
  initialState: {
    activeSpu: 'HP-VICTUS-16',
  },
  reducers: {
    setActiveSpu: (state, action) => {
      state.activeSpu = action.payload;
    },
  },
});

export const { setActiveSpu } = appSlice.actions;

export interface RootState {
  app: { activeSpu: string };
  room: any;
  device: any;
}

const store = configureStore({
  reducer: {
    app: appSlice.reducer,
    room: (state = { localUser: {}, scene: {} }) => state,
    device: (state = {}) => state,
  },
});

export type AppDispatch = typeof store.dispatch;

export default store;
