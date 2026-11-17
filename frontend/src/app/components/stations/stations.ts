import { Component, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { StationData } from '../../services/station-data';

@Component({
  imports: [RouterLink],
  selector: 'app-stations',
  styleUrl: './stations.css',
  templateUrl: './stations.html',
})
export class Stations {
  station_list = signal<any[]>([]);
  page = signal(1);
  lastPage = signal(1);
  search = signal('');
  zone = signal('');

  constructor(private stationData: StationData) { }

  ngOnInit() {
    this.loadPage();
  }

  loadPage() {
    this.stationData.getStations(this.page(), this.search(), this.zone())
      .subscribe(response => {
        this.station_list.set(response.data);
        this.lastPage.set(Math.max(1, response.total_pages));
      });
  }

  applyFilters(search: string, zone: string) {
    this.search.set(search);
    this.zone.set(zone);
    this.page.set(1);
    this.loadPage();
  }

  nextPage() {
    if (this.page() < this.lastPage()) {
      this.page.set(this.page() + 1);
      this.loadPage();
    }
  }

  previousPage() {
    if (this.page() > 1) {
      this.page.set(this.page() - 1);
      this.loadPage();
    }
  }
}