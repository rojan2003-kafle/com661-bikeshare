import { Routes } from '@angular/router';
import { Home } from './components/home/home';
import { Stations } from './components/stations/stations';
import { Station } from './components/stations/station/station';

export const routes: Routes = [
  { path: '', component: Home },
  { path: 'stations', component: Stations },
  { path: 'stations/:id', component: Station }
];